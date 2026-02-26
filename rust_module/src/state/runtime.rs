use once_cell::sync::Lazy;
use tokio::runtime::Runtime;
use reqwest::Client;

pub static RUNTIME: Lazy<Runtime> = Lazy::new(|| {
    Runtime::new().unwrap()
});

pub static GLOBAL_HTTP_CLIENT: Lazy<Client> = Lazy::new(|| {
    Client::builder()
        .tcp_nodelay(true)
        .pool_idle_timeout(std::time::Duration::from_secs(30))
        .pool_max_idle_per_host(10)
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .unwrap()
});
