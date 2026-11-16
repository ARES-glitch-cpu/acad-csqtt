//! Exercise negotiation over a real TCP TURN channel, with no external services.
use super::*;
use crate::obfs::{ObfsCipher, ObfsConfig, ObfsState};
use std::sync::atomic::AtomicUsize;
use tokio::sync::mpsc;

async fn reconnect_with_cached_workers(cached: usize, requested: usize, limit: usize) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let endpoint = format!(
        "turn:127.0.0.1:{}?transport=tcp",
        listener.local_addr().unwrap().port()
    );
    let pool = PacketPool::new(128);
    let server_pool = pool.clone();
    let key = derive_wrap_key("worker-negotiation-test").unwrap();
    let keys = crate::dtls::derive_dtls_srtp_deterministic(&key);
    let agreed = if limit == 0 {
        requested
    } else {
        requested.min(limit)
    };
    let (negotiated_tx, negotiated_rx) = oneshot::channel();
    let server_task = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let first = recv_stream_message(&mut stream).await;
        let first = StunMessage::decode(&first).unwrap();
        stream
            .write_all(&challenge_response(first.transaction()))
            .await
            .unwrap();
        let allocate = recv_stream_message(&mut stream).await;
        let allocate = assert_authenticated_request(&allocate, ALLOCATE_REQUEST);
        stream
            .write_all(&allocate_success(
                allocate.transaction(),
                "127.0.0.1:49019".parse().unwrap(),
            ))
            .await
            .unwrap();
        let permission = recv_stream_message(&mut stream).await;
        let permission = assert_authenticated_request(&permission, CREATE_PERMISSION_REQUEST);
        stream
            .write_all(&empty_authenticated_success(
                CREATE_PERMISSION_SUCCESS,
                permission.transaction(),
            ))
            .await
            .unwrap();
        let bind = recv_stream_message(&mut stream).await;
        let bind = assert_authenticated_request(&bind, CHANNEL_BIND_REQUEST);
        let channel = channel_number(&bind);
        stream
            .write_all(&empty_authenticated_success(
                CHANNEL_BIND_SUCCESS,
                bind.transaction(),
            ))
            .await
            .unwrap();

        let decoder = ObfsCipher::new(keys.client_cipher_key).unwrap();
        let encoder = ObfsCipher::new(keys.server_cipher_key).unwrap();
        let obfs = ObfsConfig::new(ObfsMode::Video);
        let state = ObfsState::new();
        let mut negotiated_tx = Some(negotiated_tx);
        loop {
            // After shutdown the next message is a STUN Refresh, not ChannelData.
            let mut prefix = [0u8; 4];
            stream.read_exact(&mut prefix).await.unwrap();
            let length = usize::from(u16::from_be_bytes([prefix[2], prefix[3]]));
            if prefix[0] < 0x40 {
                let mut wire = vec![0; 20 + length];
                wire[..4].copy_from_slice(&prefix);
                stream.read_exact(&mut wire[4..]).await.unwrap();
                let refresh = assert_authenticated_request(&wire, REFRESH_REQUEST);
                stream
                    .write_all(&refresh_zero_success(refresh.transaction()))
                    .await
                    .unwrap();
                break;
            }
            let mut body = vec![0; (length + 3) & !3];
            stream.read_exact(&mut body).await.unwrap();
            let mut packet = server_pool.acquire();
            packet.read_area()[..length].copy_from_slice(&body[..length]);
            packet.set_read_len(length).unwrap();
            decoder.unwrap(&mut packet, obfs.mode).unwrap();
            let text = std::str::from_utf8(packet.as_slice()).unwrap();
            let response = if text.starts_with("GETCONF:") {
                assert!(text.ends_with(&format!("|1|{requested}")));
                // Reproduce the server retaining the previous connection's count.
                Some(format!(
                    "TUNCONF:10.66.67.2:77.88.8.8:9000:stream-v1:workers={cached}"
                ))
            } else if text.starts_with("GETWORKERS:") {
                assert_eq!(
                    text,
                    format!("GETWORKERS:worker-negotiation-test|{requested}")
                );
                if let Some(tx) = negotiated_tx.take() {
                    tx.send(()).unwrap();
                }
                Some(format!("TUNWORKERS:{agreed}:{limit}"))
            } else if text.starts_with("DISCONNECT:") {
                Some("OK:disconnected".to_owned())
            } else {
                None
            };
            if let Some(response) = response {
                let bytes = response.as_bytes();
                packet.read_area()[..bytes.len()].copy_from_slice(bytes);
                packet.set_read_len(bytes.len()).unwrap();
                encoder.wrap(&mut packet, &obfs, &state).unwrap();
                stream
                    .write_all(&channel_data(channel, packet.as_slice()))
                    .await
                    .unwrap();
            }
        }
    });

    let cancel = CancellationToken::new();
    let stats = Arc::new(Stats::default());
    let (dispatcher, _) = Dispatcher::start(
        "127.0.0.1:0",
        None,
        pool.clone(),
        stats.clone(),
        key,
        ObfsMode::Video,
        cancel.clone(),
    )
    .await
    .unwrap();
    let target = Arc::new(AtomicUsize::new(requested));
    let (config_tx, _config_rx) = mpsc::channel(2);
    let session = tokio::spawn(run_session(
        SessionConfig {
            id: 1,
            peer: "127.0.0.1:46000".parse().unwrap(),
            turn_host: None,
            turn_port: None,
            turn_transport: TurnTransportMode::TcpTls,
            srtp_mode: SrtpMode::Wrap,
            local_port: Arc::from("9000"),
            password: Arc::from("worker-negotiation-test"),
            generation: 0,
            turn_endpoint_cursor: 0,
            salt: Arc::from(""),
            mode: ObfsMode::Video,
            wrap_key: key,
            client_wrap_key: key,
            // The configuration owner can be another worker rejected by the old count.
            get_config: false,
            server_stream_repair: Arc::new(AtomicBool::new(false)),
            repair: RepairState::new(requested),
            configured_workers: requested,
        },
        TurnCredentials {
            username: Arc::from(USERNAME),
            password: Arc::from(PASSWORD),
            server_addresses: vec![Arc::from(endpoint)].into(),
        },
        SessionRuntime {
            dispatcher: dispatcher.clone(),
            pool,
            stats,
            events: Events::new(false),
            config_tx,
            config_delivery: None,
            cancel: cancel.clone(),
            shutdown: Arc::new(ShutdownCoordinator::new()),
            ready_tx: None,
            allocation_started: None,
            allocation_ready: None,
            scale_notify: None,
            target_workers: Some(target.clone()),
            configured_workers: requested,
        },
    ));
    let result = tokio::time::timeout(Duration::from_secs(3), negotiated_rx).await;
    if matches!(result, Ok(Ok(()))) {
        tokio::time::timeout(Duration::from_secs(3), async {
            while target.load(Ordering::Acquire) != agreed {
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("the server's negotiated count was not applied");
    }
    cancel.cancel();
    let stopped = tokio::time::timeout(Duration::from_secs(5), session).await;
    dispatcher.shutdown().await;
    assert!(
        matches!(result, Ok(Ok(()))),
        "a connected non-owner worker must renegotiate the cached count"
    );
    stopped.unwrap().unwrap().unwrap();
    tokio::time::timeout(Duration::from_secs(3), server_task)
        .await
        .unwrap()
        .unwrap();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn reconnect_six_to_twelve_renegotiates_without_configuration_owner() {
    reconnect_with_cached_workers(6, 12, 0).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn reconnect_six_to_eighteen_renegotiates_without_configuration_owner() {
    reconnect_with_cached_workers(6, 18, 0).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn reconnect_twelve_to_six_can_lower_the_cached_count() {
    reconnect_with_cached_workers(12, 6, 0).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn renegotiation_respects_a_real_server_limit() {
    reconnect_with_cached_workers(6, 12, 6).await;
}
