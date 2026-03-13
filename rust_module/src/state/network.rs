use once_cell::sync::Lazy;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicU32, Ordering};
use parking_lot::RwLock;

#[derive(Debug)]
pub struct RpcNode {
    pub url: String,
    pub latency_ns: AtomicU64,
    pub fail_count: AtomicU32,
    pub is_private: bool, 
}

impl RpcNode {
    fn priority(&self) -> u64 {
        let latency = self.latency_ns.load(Ordering::Relaxed);
        let fails = self.fail_count.load(Ordering::Relaxed);
        let fail_penalty = fails as u64 * 1_000_000_000; // 1 sec per fail
        let private_bonus = if self.is_private { 0 } else { 50_000_000 }; // 50 ms bonus
        latency + fail_penalty + private_bonus
    }

    pub fn is_available(&self) -> bool {
        self.fail_count.load(Ordering::Relaxed) < 3
    }
}

pub struct RpcPoolState {
    pub nodes: Vec<RpcNode>,
    fastest_cache: RwLock<Option<String>>,
}

impl Default for RpcPoolState {
    fn default() -> Self {
        Self {
            nodes: Vec::new(),
            fastest_cache: RwLock::new(None),
        }
    }
}

impl RpcPoolState {
    pub fn get_fastest_node(&self) -> Option<String> {
        // Проверяем кэш
        {
            let cache = self.fastest_cache.read();
            if let Some(ref url) = *cache {
                if let Some(node) = self.nodes.iter().find(|n| &n.url == url) {
                    if node.is_available() {
                        return Some(url.clone());
                    }
                }
            }
        }
        
        // Ищем лучший
        let best = self.nodes.iter()
            .filter(|n| n.is_available())
            .min_by_key(|n| n.priority())?;
        
        // Обновляем кэш
        *self.fastest_cache.write() = Some(best.url.clone());
        Some(best.url.clone())
    }

    pub fn get_fastest_pool(&self, limit: usize) -> Vec<String> {
        let mut sorted: Vec<_> = self.nodes.iter()
            .filter(|n| n.is_available())
            .collect();
        sorted.sort_by_key(|n| n.priority());
        sorted.into_iter()
            .take(limit)
            .map(|n| n.url.clone())
            .collect()
    }

    pub fn update_latency(&mut self, url: &str, latency_ns: u128) {
        if let Some(node) = self.nodes.iter().find(|n| n.url == url) {
            // EMA сглаживание
            let old = node.latency_ns.load(Ordering::Relaxed);
            let new = if old == u64::MAX { latency_ns as u64 } else { (old as f64 * 0.7 + latency_ns as f64 * 0.3) as u64 };
            node.latency_ns.store(new, Ordering::Relaxed);
            node.fail_count.store(0, Ordering::Relaxed);
            *self.fastest_cache.write() = None;  // сброс кэша
        }
    }

    pub fn mark_fail(&mut self, url: &str) {
        if let Some(node) = self.nodes.iter().find(|n| n.url == url) {
            node.fail_count.fetch_add(1, Ordering::Relaxed);
            *self.fastest_cache.write() = None;
        }
    }
}

pub static RPC_POOL: Lazy<RwLock<RpcPoolState>> = Lazy::new(|| {
    RwLock::new(RpcPoolState::default())
});

pub static SHUTDOWN_FLAG: Lazy<AtomicBool> = Lazy::new(|| AtomicBool::new(false));
