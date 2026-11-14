//! Windows launcher proxy path. All credentials stay in the child environment.
use anyhow::{Context, Result, bail};
use base64::{Engine, engine::general_purpose::STANDARD};
use tokio::{io::{AsyncReadExt, AsyncWriteExt}, net::TcpStream, time::{Duration, timeout}};

pub fn configured() -> bool { std::env::var_os("CSQTT_HTTP_PROXY").is_some() }

pub fn http_proxy() -> Result<primp::Proxy> {
    let address = std::env::var("CSQTT_HTTP_PROXY").context("HTTP proxy is required")?;
    let mut proxy = primp::Proxy::all(format!("http://{address}"))?;
    let user = std::env::var("CSQTT_PROXY_USER").unwrap_or_default();
    if !user.is_empty() {
        proxy = proxy.basic_auth(&user, &std::env::var("CSQTT_PROXY_PASSWORD").unwrap_or_default());
    }
    Ok(proxy)
}

pub async fn connect(authority: &str) -> Result<TcpStream> {
    let proxy = std::env::var("CSQTT_HTTP_PROXY").context("HTTP proxy is required")?;
    // Literal proxy IP avoids any dependency on local DNS.
    let address: std::net::SocketAddr = proxy.parse().context("Proxy must be IP:port")?;
    timeout(Duration::from_secs(15), async {
        let mut stream = TcpStream::connect(address).await.context("Cannot connect to HTTP proxy")?;
        let user = std::env::var("CSQTT_PROXY_USER").unwrap_or_default();
        let password = std::env::var("CSQTT_PROXY_PASSWORD").unwrap_or_default();
        handshake(&mut stream, authority, &user, &password).await?;
        Ok(stream)
    }).await.context("HTTP proxy CONNECT timeout")?
}

async fn handshake(stream: &mut TcpStream, authority: &str, user: &str, password: &str) -> Result<()> {
        let auth = if user.is_empty() { String::new() } else {
            format!("Proxy-Authorization: Basic {}\r\n", STANDARD.encode(format!("{user}:{password}")))
        };
        let request = format!("CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n{auth}\r\n");
        stream.write_all(request.as_bytes()).await?;
        // Read exactly the header: bytes following it belong to TURN/TLS.
        let mut header = Vec::new();
        loop {
            header.push(stream.read_u8().await.context("Proxy closed CONNECT response")?);
            if header.ends_with(b"\r\n\r\n") { break; }
            if header.len() >= 16384 { bail!("HTTP proxy response header too large"); }
        }
        check_response(&header)
}

fn check_response(header: &[u8]) -> Result<()> {
    let response = std::str::from_utf8(header).context("Invalid HTTP proxy response")?;
    let mut status = response.lines().next().unwrap_or_default().split_whitespace();
    let version = status.next().unwrap_or_default();
    let code = status.next().unwrap_or_default();
    if version != "HTTP/1.1" && version != "HTTP/1.0" { bail!("Invalid HTTP proxy response"); }
    match code {
        "200" => Ok(()),
        "407" => bail!("Proxy authentication failed (407). Check credentials; this client supports HTTP Basic, not NTLM/Kerberos."),
        "403" => bail!("Proxy rejected CONNECT (403). The TURN host/port is not allowed."),
        _ => bail!("HTTP proxy CONNECT failed, status {code}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn response_codes() {
        assert!(check_response(b"HTTP/1.1 200 Connection established\r\n\r\n").is_ok());
        assert!(check_response(b"HTTP/1.0 407 Auth required\r\n\r\n").unwrap_err().to_string().contains("407"));
        assert!(check_response(b"HTTP/1.1 403 Forbidden\r\n\r\n").is_err());
        assert!(check_response(b"garbage 200\r\n\r\n").is_err());
    }

    #[tokio::test]
    async fn authenticated_connect_preserves_following_bytes() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let task = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut header = Vec::new();
            while !header.ends_with(b"\r\n\r\n") { header.push(socket.read_u8().await.unwrap()); }
            let header = String::from_utf8(header).unwrap();
            assert!(header.starts_with("CONNECT relay.example:443 HTTP/1.1\r\n"));
            assert!(header.contains(&format!("Proxy-Authorization: Basic {}\r\n", STANDARD.encode("test-user:test-pass"))));
            socket.write_all(b"HTTP/1.1 200 Connection established\r\n\r\nTURN").await.unwrap();
        });
        let mut socket = TcpStream::connect(address).await.unwrap();
        handshake(&mut socket, "relay.example:443", "test-user", "test-pass").await.unwrap();
        let mut payload = [0; 4];
        socket.read_exact(&mut payload).await.unwrap();
        assert_eq!(&payload, b"TURN");
        task.await.unwrap();
    }

    #[tokio::test]
    async fn connect_407_is_an_error() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let task = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut header = Vec::new();
            while !header.ends_with(b"\r\n\r\n") { header.push(socket.read_u8().await.unwrap()); }
            socket.write_all(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n").await.unwrap();
        });
        let mut socket = TcpStream::connect(address).await.unwrap();
        let error = handshake(&mut socket, "relay.example:443", "test-user", "wrong-pass").await.unwrap_err();
        assert!(error.to_string().contains("407"));
        task.await.unwrap();
    }
}
