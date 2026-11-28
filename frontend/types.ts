export interface Profile {
  role: string;
  share_link: string;
  client_password: string;
  dns: string;
  server: string;
  password: string;
  hashes: string;
  proxy: string;
  proxy_user: string;
  proxy_password: string;
  socks_port: string;
  http_port: string;
  workers: string;
  turn: string;
  obfs: string;
  srtp: string;
  generation: string;
  salt: string;
  internet_mode: string;
  system_proxy: string;
  tun: string;
  turn_transport: string;
  gooby: boolean;
  gooby_strategy: string;
  fingerprint: string;
  vk_auth_mode: string;
  client_ids: string;
  captcha_mode: string;
  custom_turn_ips: string;
  domain_routing: boolean;
  exclude_ru_zones: boolean;
  template_domains: boolean;
  domain_whitelist: boolean;
  direct_domains: string;
  ip_routing: boolean;
  ip_whitelist: boolean;
  direct_ips: string;
}
export interface Update { version: string; url: string }
export interface State {
  status: string; message: string; active: number; upload: number; download: number;
  ip: string; ready: boolean; logs: {time: string; message: string; level: string}[];
  revision: number; update: Update | null; updateChecking: boolean; updateMessage: string;
}
export interface Initial { profile: Profile; state: State; version: string; error: string }
export const defaults: Profile = {
  role: 'admin', share_link: '', client_password: '', dns: '',
  server: '', password: '', hashes: '', proxy: '10.0.0.1:3128', proxy_user: '', proxy_password: '',
  socks_port: '1080', http_port: '8080', workers: '6', turn: '', obfs: 'unified', srtp: 'auto',
  generation: '0', salt: '', internet_mode: 'proxy', system_proxy: '0', tun: '0',
  turn_transport: 'tcp', gooby: false, gooby_strategy: 'current', fingerprint: 'chrome',
  vk_auth_mode: 'vkcalls', client_ids: '', captcha_mode: 'auto', custom_turn_ips: '',
  domain_routing: false, exclude_ru_zones: false, template_domains: false, domain_whitelist: false,
  direct_domains: '', ip_routing: false, ip_whitelist: false, direct_ips: ''
};
