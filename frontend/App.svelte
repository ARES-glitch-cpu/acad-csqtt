<script lang="ts">
 import {onMount} from 'svelte';
 import TitleBar from './components/TitleBar.svelte';
 import Icon from './components/Icon.svelte';
 import Fields from './components/Fields.svelte';
 import UpdateDialog from './components/UpdateDialog.svelte';
 import logo from '../assets/icons/CS_logo.png';
 import {backend} from './api';
 import {defaults,type Profile,type State,type Update,type DeployResult,type DeployProgress,type DeployAction} from './types';
 import {version} from './package.json';

 type Page='connection'|'settings'|'deploy'|'routing'|'logs';
 let profile:Profile={...defaults};
 let remember=true;
 let page:Page='connection';
 let loading=true;
 let action=false;
 let error='';
 let saveMessage='';
 let proxyMessage='';
 let proxyOK=false;
 let proxyBusy=false;
 let state:State={status:'offline',message:'Готов к подключению',active:0,upload:0,download:0,ip:'',ready:false,logs:[],revision:0,update:null,updateChecking:false,updateMessage:''};
 let modal:Update|null=null;
 let dismissed='';
 let manualUpdate=false;
 let saveTimer:ReturnType<typeof setTimeout>;
 let saveRevision=0;
 let saveChain=Promise.resolve();
 let logBox:HTMLDivElement;
 let deployResult:DeployResult|null=null;
 let deployBusy=false;
 let deployProgress:DeployProgress={percent:0,message:'Готов к проверке',done:false,success:false};
 let deployError='';
 let deployActionBusy=false;
 let deployTimer:ReturnType<typeof setTimeout>;

 $: online=state.status==='online';
 $: running=state.status!=='offline';
 $: stopping=state.status==='stopping';
 $: connecting=['connecting','checking','recovering'].includes(state.status);
 $: statusTitle=({offline:'Не подключено',connecting:'Устанавливаем связь',checking:'Проверяем интернет',online:'Защищённое соединение',recovering:'Восстанавливаем связь',stopping:'Завершаем сессию',unconfirmed:'Требуется проверка'} as Record<string,string>)[state.status]||state.status;
 $: pageTitle=page==='connection'?'Обзор соединения':page==='settings'?'Параметры подключения':page==='deploy'?'Управление сервером':page==='routing'?'Маршрутизация':'Журнал событий';
 $: pageSubtitle=page==='connection'?'Единая панель управления защищённым подключением.':page==='settings'?'Профиль, транспорт и параметры локальной сети.':page==='deploy'?'Безопасная проверка, установка и обслуживание VPS через SSH.':page==='routing'?'Правила обработки доменов и IPv4-адресов в системном TUN.':'Диагностика, события ядра и состояние сессии.';
 $: if(state.update&&state.update.version!==dismissed)modal=state.update;
 $: if(manualUpdate&&!state.updateChecking){manualUpdate=false;if(state.update)modal=state.update;}

 const mb=(value:number)=>(value/1048576).toLocaleString('ru-RU',{maximumFractionDigits:2,minimumFractionDigits:2});
 function accept(next:State){
   state=next;
   if(page==='logs'&&logBox&&logBox.scrollHeight-logBox.scrollTop-logBox.clientHeight<70)
     requestAnimationFrame(()=>logBox.scrollTop=logBox.scrollHeight);
 }
 onMount(()=>{
   let disposed=false;
   let unsubscribe:undefined|(()=>void);
   let deployUnsubscribe:undefined|(()=>void);
   void backend().Initial().then(data=>{
     if(disposed)return;
     profile=data.profile;
     accept(data.state);
     error=data.error;
     loading=false;
     unsubscribe=window.runtime?.EventsOn('state',accept);
     deployUnsubscribe=window.runtime?.EventsOn('deploy-progress',(next:DeployProgress)=>{
       deployProgress=next;
       if(next.done){
         deployBusy=false;
         deployActionBusy=false;
         if(next.success){
           deployError='';
           deployTimer=setTimeout(()=>{if(!disposed&&page==='deploy')void inspectDeploy();},1200);
         }else deployError=next.message;
       }
     });
   }).catch(e=>{error=String(e);loading=false;});
   const unload=()=>{clearTimeout(saveTimer);clearTimeout(deployTimer);if(saveRevision)void flush();};
   window.addEventListener('beforeunload',unload);
   return()=>{disposed=true;unsubscribe?.();deployUnsubscribe?.();clearTimeout(saveTimer);clearTimeout(deployTimer);window.removeEventListener('beforeunload',unload);};
 });
 function chooseRole(role:'admin'|'client'){if(running)return;profile.role=role;dirty();}
 function dirty(){
   saveRevision++;
   saveMessage='Сохраняю изменения…';
   void backend().SetDraft({...profile},remember).catch(e=>error=String(e));
   clearTimeout(saveTimer);
   saveTimer=setTimeout(()=>void flush().catch(e=>error=String(e)),400);
 }
 async function flush(){
   clearTimeout(saveTimer);
   const revision=saveRevision;
   const value={...profile};
   const enabled=remember;
   saveChain=saveChain.catch(()=>{}).then(()=>backend().SaveProfile(value,enabled));
   try{
     await saveChain;
     if(saveRevision===revision){saveRevision=0;saveMessage=enabled?'Все параметры сохранены':'Сохранение отключено';}
   }catch(e){saveMessage='Не удалось сохранить';throw e;}
 }
 async function toggle(){
   if(action||stopping)return;
   action=true;error='';
   try{
     let next:State;
     if(running)next=await backend().Disconnect();
     else{await flush();next=await backend().Connect();}
     if(next.revision>=state.revision)accept(next);
   }catch(e){error=String(e);if(!running)page='settings';}
   finally{action=false;}
 }
 async function mode(key:keyof Profile,value:string){
   if(key==='internet_mode'&&value==='proxy'){
     profile.gooby=false;
     profile.turn_transport='tcp';
   }
   profile[key]=value;
   dirty();
   if(key==='system_proxy'){
     try{await flush();await backend().SetSystemProxy(value==='1');}
     catch(e){error=String(e);}
   }
 }
 async function checkProxy(){
   proxyBusy=true;proxyMessage='Проверяю доступность HTTP CONNECT…';
   try{await backend().CheckProxy({...profile});proxyOK=true;proxyMessage='Прокси доступен · CONNECT :443 разрешён';}
   catch(e){proxyOK=false;proxyMessage=String(e);}
   finally{proxyBusy=false;}
 }
 async function checkUpdates(){
   manualUpdate=true;
   state={...state,updateChecking:true};
   await flush();
   await backend().CheckUpdates();
 }
 async function openUpdate(){
   try{await backend().OpenUpdate();dismissed=modal?.version||'';modal=null;}
   catch(e){error=String(e);}
 }
 function later(){dismissed=modal?.version||state.update?.version||'';modal=null;}
 async function copyLogs(){
   try{await navigator.clipboard.writeText(state.logs.map(l=>l.time+' '+l.message).join('\\n'));}
   catch{error='Не удалось скопировать журнал. Используйте экспорт.';}
 }
 async function hide(){
   try{await flush();await backend().HideToTray();}
   catch(e){error=String(e);}
 }
 async function inspectDeploy(){
   deployBusy=true;deployError='';deployResult=null;
   deployProgress={percent:0,message:'Подключение по SSH и чтение инвентаризации…',done:false,success:false};
   try{
     await flush();
     deployResult=await backend().InspectDeployServer();
     deployProgress={percent:deployResult.needsTrust?0.1:1,message:deployResult.message,done:false,success:false};
   }catch(e){deployError=String(e);}
   finally{deployBusy=false;}
 }
 async function trustDeployKey(){
   if(!deployResult?.presentedFingerprint)return;
   try{
     deployBusy=true;deployError='';
     await backend().TrustDeployHostKey(deployResult.presentedFingerprint);
     await inspectDeploy();
   }catch(e){deployError=String(e);}
   finally{deployBusy=false;}
 }
 async function startDeploy(action:DeployAction){
   if(deployActionBusy||deployBusy)return;
   if(action.destructive&&!window.confirm('ВНИМАНИЕ: '+action.title+' может остановить и удалить серверные данные. У вас есть резервная копия? Продолжить?'))return;
   if(action.kind==='install'&&!window.confirm('Установить CSQTT на '+profile.deploy_host+'? Сервер пройдёт повторную SSH-проверку.'))return;
   try{
     deployActionBusy=true;deployBusy=true;deployError='';
     deployProgress={percent:0,message:'Подготовка операции…',done:false,success:false};
     await flush();
     await backend().StartDeploy(action.id);
   }catch(e){deployError=String(e);deployActionBusy=false;deployBusy=false;}
 }
 function deployPanelURL(){
   const host=profile.deploy_host.trim();
   const port=profile.deploy_web_port.trim()||'46002';
   const secret=profile.deploy_secret_path.trim().replace(/^\\/+/, '');
   return host?'https://'+host+':'+port+(secret?'/'+secret:''):'';
 }
 async function copyDeployPanel(){
   const value=deployPanelURL();
   if(!value)return;
   try{await navigator.clipboard.writeText(value);}catch{deployError='Не удалось скопировать ссылку панели.';}
 }
</script>

<TitleBar connected={online} {loading} onWindowError={message=>error=message}/>
<div class="desktop-shell">
 <aside class="sidebar">
  <div class="brand-lockup">
   <div class="brand-mark"><img src={logo} alt="CSQTT"/></div>
   <div><strong>CSQTT</strong><span>SECURE NETWORK</span></div>
  </div>
  <div class="sidebar-caption">РАБОЧЕЕ ПРОСТРАНСТВО</div>
  <nav class="main-nav" aria-label="Основная навигация">
   <button class:active={page==='connection'} class="nav-link" on:click={()=>page='connection'}>
    <span class="nav-icon"><Icon name="monitor" size={19}/></span><span>Обзор</span><kbd>01</kbd>
   </button>
   <button class:active={page==='settings'} class="nav-link" on:click={()=>page='settings'}>
    <span class="nav-icon"><Icon name="settings" size={19}/></span><span>Настройки</span><kbd>02</kbd>
   </button>
   <button class:active={page==='deploy'} class="nav-link" on:click={()=>page='deploy'}>
    <span class="nav-icon"><Icon name="server" size={19}/></span><span>Деплой</span><kbd>03</kbd>
   </button>
   <button class:active={page==='routing'} class="nav-link" on:click={()=>page='routing'}>
    <span class="nav-icon"><Icon name="route" size={19}/></span><span>Роутинг</span><kbd>04</kbd>
   </button>
   <button class:active={page==='logs'} class="nav-link" on:click={()=>page='logs'}>
    <span class="nav-icon"><Icon name="terminal" size={19}/></span><span>Журнал</span><kbd>05</kbd>
   </button>
  </nav>
  <div class="sidebar-spacer"></div>
  <div class="sidebar-status" class:connected={online}>
   <span class="status-orb"></span>
   <div><strong>{online?'Туннель активен':connecting?'Подключение…':'Туннель отключён'}</strong><small>{online?'Трафик защищён':connecting?'Ожидание ответа':'Готов к запуску'}</small></div>
  </div>
  <div class="sidebar-bottom">
   <div class="user-chip"><span class="avatar">{profile.role==='client'?'C':'A'}</span><div><strong>{profile.role==='client'?'Клиент':'Администратор'}</strong><small>Профиль подключения</small></div><button title="Открыть настройки" on:click={()=>page='settings'}><Icon name="settings" size={16}/></button></div>
   <div class="sidebar-meta"><span>CSQTT DESKTOP</span><span>v{version}</span></div>
  </div>
 </aside>

 <main class="workspace">
  <header class="workspace-header">
   <div><div class="breadcrumb"><span>CSQTT</span><i>/</i><span>{page==='connection'?'Панель управления':page==='settings'?'Конфигурация':'События'}</span></div><h1>{pageTitle}</h1><p>{pageSubtitle}</p></div>
   <div class="header-actions">
    <div class="connection-pill" class:online><span></span>{statusTitle}</div>
    <button class="tray-action" title="Свернуть программу в системный трей" on:click={hide}><Icon name="minimise" size={16}/><span>В трей</span></button>
   </div>
  </header>

  {#if error}
   <div class="notice error" role="alert"><Icon name="alert" size={18}/><span>{error}</span><button aria-label="Закрыть сообщение" on:click={()=>error=''}><Icon name="x" size={16}/></button></div>
  {/if}

  {#if page==='connection'}
   <section class="overview-page">
    <div class="overview-grid">
     <section class="hero-panel" class:online class:connecting>
      <div class="hero-grid-glow"></div>
      <div class="hero-top"><span class="eyebrow"><i></i> SECURE TUNNEL <b>·</b> DESKTOP CLIENT</span><span class="hero-version">BUILD {version}</span></div>
      <div class="hero-main">
       <div class="hero-copy">
        <span class="hero-label">{online?'ЗАЩИЩЁННЫЙ КАНАЛ АКТИВЕН':'ВАША СЕТЬ ПОД КОНТРОЛЕМ'}</span>
        <h2>{online?'Вы в защищённой сети':'Подключитесь к своей сети'}</h2>
        <p>{state.message}</p>
        <div class="hero-tags"><span><Icon name="shield" size={14}/>{profile.tun==='1'?'Системный TUN':'Локальный прокси'}</span><span><Icon name="server" size={14}/>{profile.internet_mode==='proxy'?'Через прокси':'Прямое соединение'}</span></div>
       </div>
       <div class="power-stage">
        <div class="power-halo"></div><div class="power-orbit orbit-a"></div><div class="power-orbit orbit-b"></div>
        <button class="power-button" class:online class:connecting class:stopping disabled={loading||action||stopping} on:click={toggle} aria-label={stopping?'Отключение':running?'Отключить':'Подключить'}>
         <span class="power-face"><Icon name="power" size={34}/><b>{stopping?'STOP':running?'STOP':'START'}</b></span>
        </button>
        <span class="power-caption">{running?'ЗАВЕРШИТЬ СЕССИЮ':'ЗАПУСТИТЬ СЕССИЮ'}</span>
       </div>
      </div>
      <div class="hero-footer"><div><span class="pulse-dot" class:online></span><span>{online?'Канал работает в штатном режиме':connecting?'Выполняется согласование транспорта':'Ожидание подключения'}</span></div><span>END-TO-END · CSQTT CORE</span></div>
     </section>

     <aside class="metrics-column">
      <section class="metric-card primary-metric"><div class="metric-top"><span>АКТИВНЫЕ ПОТОКИ</span><span class="metric-icon"><Icon name="server" size={17}/></span></div><strong>{state.active.toLocaleString('ru-RU')}</strong><small>{online?'Потоки работают':'Нет активных потоков'}</small><div class="metric-track"><i style={"width:"+Math.min(100,state.active/Math.max(1,Number(profile.workers)||1)*100)+"%"}></i></div></section>
      <section class="metric-card"><div class="metric-top"><span>ОТПРАВЛЕНО</span><span class="metric-icon cyan"><Icon name="globe" size={17}/></span></div><strong>{mb(state.upload)} <em>МБ</em></strong><small>Исходящий трафик</small></section>
      <section class="metric-card"><div class="metric-top"><span>ПОЛУЧЕНО</span><span class="metric-icon violet"><Icon name="download" size={17}/></span></div><strong>{mb(state.download)} <em>МБ</em></strong><small>Входящий трафик</small></section>
     </aside>
    </div>

    <div class="section-row"><div><span class="section-kicker">БЫСТРЫЕ ПАРАМЕТРЫ</span><h2>Управление сетью</h2></div><button class="inline-link" on:click={()=>page='settings'}>Все настройки <Icon name="arrow" size={15}/></button></div>
    <div class="quick-grid">
     <section class="quick-card"><div class="quick-icon"><Icon name="globe" size={19}/></div><div class="quick-copy"><strong>Корпоративный прокси</strong><small>{profile.internet_mode==='proxy'?'HTTP CONNECT · порт 443':'Прямой выход в интернет'}</small></div><label class="switch" aria-label="Корпоративный прокси"><input type="checkbox" checked={profile.internet_mode==='proxy'} disabled={running} on:change={e=>void mode('internet_mode',e.currentTarget.checked?'proxy':'direct')}/><span></span></label></section>
     <section class="quick-card"><div class="quick-icon"><Icon name="shield" size={19}/></div><div class="quick-copy"><strong>Системный TUN</strong><small>{profile.tun==='1'?'Весь IPv4-трафик через туннель':'Только приложения через локальный прокси'}</small></div><label class="switch" aria-label="Системный TUN"><input type="checkbox" checked={profile.tun==='1'} disabled={running} on:change={e=>void mode('tun',e.currentTarget.checked?'1':'0')}/><span></span></label></section>
     <section class="quick-card"><div class="quick-icon"><Icon name="settings" size={19}/></div><div class="quick-copy"><strong>Системный прокси ОС</strong><small>{profile.system_proxy==='1'?'Автоматически настроен':'Не изменяет настройки ОС'}</small></div><label class="switch" aria-label="Системный прокси ОС"><input type="checkbox" checked={profile.system_proxy==='1'} on:change={e=>void mode('system_proxy',e.currentTarget.checked?'1':'0')}/><span></span></label></section>
    </div>

    <div class="bottom-grid">
     <section class="detail-card"><div class="section-row compact"><div><span class="section-kicker">ПОДКЛЮЧЕНИЕ</span><h2>Параметры сессии</h2></div><span class="mini-badge" class:online>{online?'ONLINE':'OFFLINE'}</span></div>
      <div class="detail-list"><div><span>Сервер</span><strong>{profile.server||'Не задан'}</strong></div><div><span>Внешний IP</span><strong>{state.ip||'—'}</strong></div><div><span>Транспорт</span><strong>TURN · TCP / 443</strong></div><div><span>Рабочих потоков</span><strong>{profile.workers}</strong></div></div>
     </section>
     <section class="detail-card endpoints-card"><div class="section-row compact"><div><span class="section-kicker">ЛОКАЛЬНЫЕ АДРЕСА</span><h2>Точки доступа</h2></div><span class="endpoint-mark"><Icon name="monitor" size={18}/></span></div>
      <div class="endpoint-row"><div><span class="endpoint-dot socks"></span><div><strong>SOCKS5</strong><small>127.0.0.1:{profile.socks_port}</small></div></div><button on:click={()=>void navigator.clipboard?.writeText('127.0.0.1:'+profile.socks_port)} title="Копировать SOCKS5"><Icon name="copy" size={15}/></button></div>
      <div class="endpoint-row"><div><span class="endpoint-dot http"></span><div><strong>HTTP Proxy</strong><small>127.0.0.1:{profile.http_port}</small></div></div><button on:click={()=>void navigator.clipboard?.writeText('127.0.0.1:'+profile.http_port)} title="Копировать HTTP"><Icon name="copy" size={15}/></button></div>
      <button class="test-link" disabled={!state.ready||state.status==='checking'} on:click={()=>void backend().CheckInternet()}><Icon name="refresh" size={15}/> Проверить интернет-соединение</button>
     </section>
    </div>
   </section>
  {:else if page==='settings'}
   <section class="settings-page">
    <div class="settings-intro"><div><span class="section-kicker">ЛИЧНАЯ КОНФИГУРАЦИЯ</span><h2>Параметры клиента</h2><p>Все изменения автоматически сохраняются в локальный профиль.</p></div><span class="save-indicator" class:saved={saveMessage.includes('сохранены')}><i></i>{saveMessage||'Автосохранение включено'}</span></div>
    <div class="role-panel"><div><strong>Тип профиля</strong><small>Выберите, как вы подключаетесь к серверу CSQTT.</small></div><div class="role-selector"><button class:chosen={profile.role!=='client'} disabled={running} on:click={()=>chooseRole('admin')}>Администратор</button><button class:chosen={profile.role==='client'} disabled={running} on:click={()=>chooseRole('client')}>Клиент</button></div></div>
    <div class="settings-grid">
     {#if profile.role==='client'}
      <section class="settings-card wide"><div class="settings-card-head"><span class="settings-symbol"><Icon name="shield" size={18}/></span><div><h3>Профиль клиента</h3><p>Вставьте персональную ссылку, полученную от администратора.</p></div></div>
       <label class="field"><span>Ссылка подключения csqtt://</span><textarea disabled={running} rows="4" bind:value={profile.share_link} on:input={dirty} spellcheck="false" placeholder="csqtt://..."></textarea><small>Если ссылка содержит пароль и хеши, они будут заполнены автоматически.</small></label>
       <Fields disabled={running} bind:profile changed={dirty} fields={[{key:'client_password',label:'Пароль клиента (если отсутствует в ссылке)',secret:true}]}/>
       <label class="field"><span>Резервные VK-хеши</span><textarea disabled={running} rows="3" bind:value={profile.hashes} on:input={dirty} spellcheck="false"></textarea><small>До 6 хешей или ссылок звонков.</small></label>
      </section>
     {:else}
      <section class="settings-card"><div class="settings-card-head"><span class="settings-symbol"><Icon name="server" size={18}/></span><div><h3>Сервер CSQTT</h3><p>Адрес и параметры авторизации.</p></div></div>
       <Fields disabled={running} bind:profile changed={dirty} fields={[{key:'server',label:'Адрес сервера · IP:порт или домен:порт'},{key:'password',label:'Пароль сервера',secret:true}]}/>
       <label class="field"><span>VK-хеши или ссылки звонков</span><textarea disabled={running} rows="4" bind:value={profile.hashes} on:input={dirty} spellcheck="false" placeholder="По одному значению на строку"></textarea><small>От 1 до 6 значений.</small></label>
      </section>
     {/if}
     <section class="settings-card"><div class="settings-card-head"><span class="settings-symbol cyan"><Icon name="globe" size={18}/></span><div><h3>Корпоративная сеть</h3><p>Параметры выхода через HTTP CONNECT.</p></div></div>
      <Fields disabled={running} bind:profile changed={dirty} fields={[{key:'proxy',label:'Адрес прокси · IPv4:порт'},{key:'proxy_user',label:'Логин'},{key:'proxy_password',label:'Пароль прокси',secret:true}]}/>
      <button class="secondary-button" disabled={proxyBusy} on:click={checkProxy}><Icon name="refresh" size={15}/>{proxyBusy?'Проверяю…':'Проверить прокси :443'}</button>
      {#if proxyMessage}<p class="feedback" class:success={proxyOK} role="status">{proxyMessage}</p>{/if}
     </section>
     <section class="settings-card"><div class="settings-card-head"><span class="settings-symbol violet"><Icon name="settings" size={18}/></span><div><h3>Туннель и транспорт</h3><p>Параметры ядра, маскировки и TURN.</p></div></div>
      <Fields disabled={running} bind:profile changed={dirty} fields={[{key:'workers',label:'Количество потоков'},{key:'turn_transport',label:'Транспорт TURN',options:['udp','tcp']},{key:'obfs',label:'Обфускация',options:['unified','audio','video']},{key:'srtp',label:'Режим SRTP',options:['auto','wrap','dtls']},{key:'turn',label:'TURN-хост',hint:'Необязательно · домен или IP без порта'},{key:'custom_turn_ips',label:'Пользовательские TURN-IP',hint:'Свой список имеет приоритет над выбранной подсетью.'},{key:'dns',label:'DNS-серверы IPv4',hint:'Через запятую. Пустое значение — DNS сервера.'}]}/>
      <label class="field"><span>Готовая TURN-подсеть VK</span>
       <select disabled={running||!!profile.custom_turn_ips.trim()} bind:value={profile.turn_subnet} on:change={dirty}>
        <option value="">Авто · адреса из ответа VK</option>
        <option value="95.163.34.0/24">95.163.34.0/24</option>
        <option value="91.231.135.0/24">91.231.135.0/24</option>
        <option value="90.156.232.0/21">90.156.232.0/21</option>
        <option value="193.203.43.0/24">193.203.43.0/24</option>
        <option value="185.180.200.0/22">185.180.200.0/22</option>
       </select><small>Пустой выбор оставляет адреса, выданные VK. Случайные публичные TURN-серверы не используются.</small>
      </label>
      <label class="field"><span>Количество TURN-IP</span>
       <select disabled={running||!profile.turn_subnet||!!profile.custom_turn_ips.trim()} bind:value={profile.turn_ip_limit} on:change={dirty}>
        <option value="ALL">Все адреса</option><option value="1">1</option><option value="2">2</option><option value="4">4</option><option value="9">9</option>
       </select>
      </label>
     </section>
     <section class="settings-card"><div class="settings-card-head"><span class="settings-symbol cyan"><Icon name="shield" size={18}/></span><div><h3>Gooby · маскировка TCP</h3><p>Встроенный SOCKS5 движок Android 2.5.3, только для прямого TCP/TLS.</p></div></div>
      <label class="save-toggle"><input type="checkbox" checked={profile.gooby} disabled={running||profile.turn_transport!=='tcp'||profile.internet_mode==='proxy'} on:change={e=>{profile.gooby=e.currentTarget.checked;dirty();}}/><span><b>Включить Gooby</b><small>Нельзя использовать с UDP или корпоративным HTTP CONNECT.</small></span></label>
      <Fields disabled={running||!profile.gooby} bind:profile changed={dirty} fields={[{key:'gooby_strategy',label:'Стратегия',options:['current','gentle','extended']}]}/>
      <div class="config-path"><Icon name="info" size={15}/><span>Gooby обрабатывает только начальные TCP/TLS-пакеты соединения. Уже установленный трафик не изменяется.</span></div>
     </section>
     <section class="settings-card"><div class="settings-card-head"><span class="settings-symbol violet"><Icon name="fingerprint" size={18}/></span><div><h3>Параметры VK и TLS</h3><p>Совместимость аутентификации и TLS ClientHello.</p></div></div>
      <Fields disabled={running} bind:profile changed={dirty} fields={[{key:'fingerprint',label:'TLS Client fingerprint',options:['chrome','safari','firefox','edge','opera']},{key:'vk_auth_mode',label:'Авторизация VK',options:['vkcalls']},{key:'captcha_mode',label:'Обработка капчи',options:['auto','rjs','wv']},{key:'client_ids',label:'Дополнительные Client IDs',hint:'Необязательно · значения через запятую'}]}/>
     </section>
     <section class="settings-card"><div class="settings-card-head"><span class="settings-symbol amber"><Icon name="monitor" size={18}/></span><div><h3>Локальные порты</h3><p>Адреса прокси, доступных на этом компьютере.</p></div></div>
      <Fields disabled={running} bind:profile changed={dirty} fields={[{key:'socks_port',label:'Порт SOCKS5'},{key:'http_port',label:'Порт HTTP'},{key:'generation',label:'Поколение'},{key:'salt',label:'Salt',secret:true}]}/>
     </section>
     <section class="settings-card"><div class="settings-card-head"><span class="settings-symbol"><Icon name="shield" size={18}/></span><div><h3>Хранение профиля</h3><p>Сохранение параметров на этом компьютере.</p></div></div>
      <label class="save-toggle"><input type="checkbox" bind:checked={remember} on:change={dirty}/><span><b>Запоминать настройки</b><small>Пароли и параметры будут восстановлены при следующем запуске.</small></span></label>
      <div class="config-path"><Icon name="check" size={15}/><span>Изменения записываются автоматически в пользовательский config.json (папка CSQTT).</span></div>
     </section>
     <section class="settings-card update-card"><div class="settings-card-head"><span class="settings-symbol cyan"><Icon name="refresh" size={18}/></span><div><h3>Обновления</h3><p>Текущая версия v{version}</p></div></div>
      <button class="secondary-button" disabled={state.updateChecking} on:click={()=>void checkUpdates().catch(e=>error=String(e))}><Icon name="refresh" size={15}/>{state.updateChecking?'Проверяю…':'Проверить обновления'}</button>
      <p class="feedback">{state.updateMessage}</p>
      {#if state.update}<button class="inline-link" on:click={()=>modal=state.update}>Доступно обновление <Icon name="arrow" size={15}/></button>{/if}
     </section>
    </div>
   </section>
  {:else if page==='deploy'}
   <section class="settings-page deploy-page">
    <div class="settings-intro"><div><span class="section-kicker">SSH · VPS MANAGEMENT</span><h2>Подключение к серверу</h2><p>Инвентаризация выполняется только для чтения. Перед любыми изменениями приложение проверит SSH-ключ и повторно просканирует VPS.</p></div><span class="save-indicator" class:saved={!!profile.deploy_host_key}><i></i>{profile.deploy_host_key?'SSH host key закреплён':'Требуется первое доверие ключу'}</span></div>
    <div class="settings-grid">
     <section class="settings-card"><div class="settings-card-head"><span class="settings-symbol cyan"><Icon name="server" size={18}/></span><div><h3>SSH-доступ к VPS</h3><p>Обычный пароль или ключ Ed25519/RSA/OpenSSH.</p></div></div>
      <Fields disabled={deployBusy} bind:profile changed={dirty} fields={[{key:'deploy_host',label:'IP или домен VPS'},{key:'deploy_user',label:'SSH-пользователь'},{key:'deploy_ssh_port',label:'SSH-порт'},{key:'deploy_password',label:'SSH / sudo пароль',secret:true}]}/>
      <label class="field"><span>Приватный SSH-ключ (необязательно)</span><textarea rows="6" disabled={deployBusy} bind:value={profile.deploy_private_key} on:input={dirty} spellcheck="false" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"></textarea><small>Если задан ключ, для SSH используется он; пароль выше может использоваться для sudo.</small></label>
      <Fields disabled={deployBusy} bind:profile changed={dirty} fields={[{key:'deploy_key_passphrase',label:'Парольная фраза ключа',secret:true}]}/>
      <button class="secondary-button" disabled={deployBusy||!profile.deploy_host.trim()} on:click={()=>void inspectDeploy()}><Icon name="search" size={15}/>{deployBusy?'Проверяю…':'Проверить SSH и сервер'}</button>
      {#if deployError}<p class="feedback" role="alert">{deployError}</p>{/if}
     </section>
     <section class="settings-card"><div class="settings-card-head"><span class="settings-symbol violet"><Icon name="settings" size={18}/></span><div><h3>Параметры установки</h3><p>Порты и способ запуска серверного экземпляра.</p></div></div>
      <Fields disabled={deployBusy} bind:profile changed={dirty} fields={[{key:'deploy_peer_port',label:'UDP peer-порт'},{key:'deploy_web_port',label:'WEB-порт'},{key:'deploy_mode',label:'Режим установки',options:['systemd','docker']},{key:'deploy_instance',label:'Экземпляр',options:['main','side']}]}/>
      <div class="config-path"><Icon name="shield" size={15}/><span>Основной сервер: 46000/46002. Второй экземпляр: 46100/46102. Проверка не останавливает работающие службы.</span></div>
     </section>
     <section class="settings-card wide"><div class="settings-card-head"><span class="settings-symbol amber"><Icon name="key" size={18}/></span><div><h3>Авторизация и веб-панель</h3><p>Эти данные нужны только для первоначальной установки и сохраняются в config.json.</p></div></div>
      <div class="settings-grid deploy-secrets">
       <div><Fields disabled={deployBusy} bind:profile changed={dirty} fields={[{key:'deploy_main_password',label:'Главный пароль CSQTT',secret:true},{key:'deploy_web_login',label:'Логин веб-панели'},{key:'deploy_web_password',label:'Пароль веб-панели',secret:true}]}/></div>
       <div><Fields disabled={deployBusy} bind:profile changed={dirty} fields={[{key:'deploy_secret_path',label:'Секретный путь панели',hint:'Необязательно, без начального /'}]}/>
        <div class="known-host"><span>ЗАКРЕПЛЁННЫЙ SSH FINGERPRINT</span><code>{profile.deploy_host_key||'Пока не подтверждён'}</code></div>
        {#if deployPanelURL()}<div class="deploy-panel-actions"><button class="secondary-button" on:click={()=>void copyDeployPanel()}><Icon name="copy" size={15}/>Копировать ссылку</button><button class="secondary-button" on:click={()=>window.open(deployPanelURL(),'_blank','noopener')}><Icon name="globe" size={15}/>Открыть панель</button></div>{/if}
       </div>
      </div>
     </section>
    </div>

    {#if deployResult}
     <section class="deploy-result">
      {#if deployResult.needsTrust}
       <div class="hostkey-warning">
        <div class="settings-card-head"><span class="settings-symbol amber"><Icon name="shield" size={18}/></span><div><h3>{deployResult.keyChanged?'SSH-ключ сервера изменился':'Новый SSH-ключ сервера'}</h3><p>Деплой заблокирован, пока вы не сверите отпечаток с консолью VPS.</p></div></div>
        {#if deployResult.expectedFingerprint}<div class="known-host"><span>РАНЕЕ ЗАПОМНЕН</span><code>{deployResult.expectedFingerprint}</code></div>{/if}
        <div class="known-host"><span>СЕРВЕР ПРЕДСТАВИЛ</span><code>{deployResult.presentedFingerprint}</code></div>
        <p>Проверьте fingerprint независимым способом на VPS. Не подтверждайте ключ, если отпечаток не совпадает.</p>
        <button class="secondary-button" disabled={deployBusy} on:click={()=>void trustDeployKey()}><Icon name="check" size={15}/>Я сверил fingerprint и доверяю этому ключу</button>
       </div>
      {:else}
       <div class="section-row"><div><span class="section-kicker">READ-ONLY INVENTORY</span><h2>Результат проверки сервера</h2></div><span class="mini-badge online">ПРОВЕРЕНО</span></div>
       <div class="deploy-summary">
        <div><span>VPS</span><strong>{deployResult.host}:{deployResult.port}</strong></div>
        <div><span>Архитектура</span><strong>{deployResult.inventory?.architecture||'Не определена'}</strong></div>
        <div><span>Найдено серверов</span><strong>{deployResult.inventory?.servers.length??0}</strong></div>
        <div><span>Занятые порты</span><strong>{deployResult.inventory?.busy.length??0}</strong></div>
       </div>
       {#if deployResult.inventory?.servers.length}
        <div class="inventory-list">
         {#each deployResult.inventory.servers as server}
          <div class="inventory-item"><div><strong>{server.name||'CSQTT'}</strong><small>{server.place} · {server.runtime} · {server.state} · {server.version||'версия неизвестна'}</small></div><span>{server.peerPort||'—'} / {server.webPort||'—'}</span></div>
         {/each}
        </div>
       {:else}
        <p class="feedback">На VPS не найдены управляемые экземпляры CSQTT.</p>
       {/if}
       {#if deployResult.inventory?.busy.length}
        <div class="inventory-list">
         {#each deployResult.inventory.busy as item}
          <div class="inventory-item"><div><strong>Занят порт {item.port}/{item.protocol.toUpperCase()}</strong><small>{item.holder}</small></div><span>BUSY</span></div>
         {/each}
        </div>
       {/if}
       {#if deployResult.notes.length}
        <div class="deploy-notes">{#each deployResult.notes as note}<p><Icon name="info" size={15}/>{note}</p>{/each}</div>
       {/if}
       <div class="section-row"><div><span class="section-kicker">РАЗРЕШЁННЫЕ ДЕЙСТВИЯ</span><h2>Что можно сделать</h2></div></div>
       {#if deployResult.actions.length}
        <div class="deploy-actions">
         {#each deployResult.actions as action}
          <div class="deploy-action-card"><div><strong>{action.title}</strong><small>{action.detail}</small><span class="action-ports">UDP {action.peerPort} · WEB {action.webPort} · {action.instance}</span></div>
           <button class:danger={action.destructive} class="secondary-button" disabled={deployActionBusy||deployBusy} on:click={()=>void startDeploy(action)}>{action.destructive?'Подтвердить действие':action.kind==='update'?'Обновить':'Установить'}</button>
          </div>
         {/each}
        </div>
       {:else}
        <div class="empty-logs"><span><Icon name="shield" size={28}/></span><strong>Нет безопасных действий</strong><p>Проверьте заметки выше. Возможно, сервером управляет другая программа.</p></div>
       {/if}
      {/if}
     </section>
    {/if}

    {#if deployBusy||deployProgress.done}
     <section class="deploy-progress">
      <div><strong>{deployProgress.message}</strong><span>{Math.round(deployProgress.percent*100)}%</span></div>
      <div class="progress-track"><i style={"width:"+Math.max(0,Math.min(100,deployProgress.percent*100))+"%"}></i></div>
     </section>
    {/if}
   </section>
  {:else if page==='routing'}
   <section class="settings-page routing-page">
    <div class="settings-intro"><div><span class="section-kicker">ПРАВИЛА ТРАФИКА</span><h2>Маршрутизация</h2><p>Списки применяются Rust-ядром в системном TUN. В режиме локального прокси другие приложения не перенаправляются.</p></div></div>
    <div class="settings-grid">
     <section class="settings-card"><div class="settings-card-head"><span class="settings-symbol cyan"><Icon name="globe" size={18}/></span><div><h3>Маршрутизация доменов</h3><p>Правила обработки доменных имён.</p></div></div>
      <label class="save-toggle"><input type="checkbox" checked={profile.domain_routing} disabled={running} on:change={e=>{profile.domain_routing=e.currentTarget.checked;dirty();}}/><span><b>Включить правила доменов</b><small>Использовать список ниже при работе системного TUN.</small></span></label>
      <label class="save-toggle"><input type="checkbox" checked={profile.domain_whitelist} disabled={running||!profile.domain_routing} on:change={e=>{profile.domain_whitelist=e.currentTarget.checked;dirty();}}/><span><b>Белый список</b><small>Туннелировать только перечисленные домены; выключено — чёрный список.</small></span></label>
      <label class="field"><span>Домены</span><textarea rows="7" disabled={running||!profile.domain_routing} bind:value={profile.direct_domains} on:input={dirty} spellcheck="false" placeholder="example.com&#10;*.example.net&#10;vk.com"></textarea><small>По одному домену или шаблону на строку.</small></label>
      <label class="save-toggle"><input type="checkbox" checked={profile.template_domains} disabled={running||!profile.domain_routing} on:change={e=>{profile.template_domains=e.currentTarget.checked;dirty();}}/><span><b>Учитывать шаблонные домены</b><small>Обрабатывать записи вида *.example.com.</small></span></label>
      <label class="save-toggle"><input type="checkbox" checked={profile.exclude_ru_zones} disabled={running||!profile.domain_routing} on:change={e=>{profile.exclude_ru_zones=e.currentTarget.checked;dirty();}}/><span><b>Исключить зоны RU / SU / РФ</b><small>Применять системное исключение доменных зон.</small></span></label>
     </section>
     <section class="settings-card"><div class="settings-card-head"><span class="settings-symbol violet"><Icon name="route" size={18}/></span><div><h3>Маршрутизация IPv4</h3><p>Адреса, диапазоны и CIDR.</p></div></div>
      <label class="save-toggle"><input type="checkbox" checked={profile.ip_routing} disabled={running} on:change={e=>{profile.ip_routing=e.currentTarget.checked;dirty();}}/><span><b>Включить IP-маршрутизацию</b><small>Правила применяются к IPv4-адресам.</small></span></label>
      <label class="save-toggle"><input type="checkbox" checked={profile.ip_whitelist} disabled={running||!profile.ip_routing} on:change={e=>{profile.ip_whitelist=e.currentTarget.checked;dirty();}}/><span><b>Белый список</b><small>Туннелировать только указанные IP; выключено — чёрный список.</small></span></label>
      <label class="field"><span>IPv4 / CIDR / диапазоны</span><textarea rows="7" disabled={running||!profile.ip_routing} bind:value={profile.direct_ips} on:input={dirty} spellcheck="false" placeholder="192.0.2.10&#10;198.51.100.0/24&#10;203.0.113.10-203.0.113.20"></textarea><small>По одному правилу на строку.</small></label>
     </section>
    </div>
   </section>
  {:else}
   <section class="logs-page">
    <div class="logs-heading"><div><span class="section-kicker">СИСТЕМНЫЕ СОБЫТИЯ</span><h2>Диагностика соединения</h2><p>Здесь отображаются сообщения приложения и Rust-ядра. Секреты скрываются перед выводом.</p></div><div class="log-actions"><span>{state.logs.length} записей</span><button class="secondary-button" on:click={copyLogs}><Icon name="copy" size={15}/>Копировать</button><button class="secondary-button" on:click={()=>void backend().ExportLog().catch(e=>error=String(e))}><Icon name="download" size={15}/>Экспорт</button></div></div>
    <div class="log-console" bind:this={logBox} role="textbox" aria-readonly="true" aria-multiline="true" tabindex="0" aria-label="Журнал событий">
     {#if state.logs.length}
      {#each state.logs as line,i}
       <div class="log-line" class:error-line={line.level==='error'}><span class="log-index">{String(i+1).padStart(3,'0')}</span><time>{line.time}</time><span class="log-tag">{line.level==='error'?'ERROR':'CORE'}</span><span class="log-message">{line.message}</span></div>
      {/each}
     {:else}
      <div class="empty-logs"><span><Icon name="terminal" size={28}/></span><strong>Событий пока нет</strong><p>После запуска подключения здесь появится диагностика.</p></div>
     {/if}
    </div>
   </section>
  {/if}

  <footer class="workspace-footer"><span><i></i> Конфигурация хранится локально на вашем устройстве</span><span>CSQTT DESKTOP <b>·</b> v{version}</span></footer>
 </main>
</div>
<UpdateDialog update={modal} current={version} {later} open={()=>void openUpdate()}/>
