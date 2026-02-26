use std::sync::{Arc, RwLock};
use once_cell::sync::Lazy;
use std::sync::atomic::AtomicBool;

#[derive(Debug, Clone)]
pub struct RpcNode {
    pub url: String,
    pub latency: u128,
    pub is_private: bool, 
    pub fails: u32,
}

#[derive(Debug, Default)]
pub struct RpcPoolState {
    pub nodes: Vec<RpcNode>,
}

impl RpcPoolState {
    pub fn get_fastest_node(&self) -> Option<String> {
        self.nodes.iter()
            .filter(|n| n.fails < 3)
            .min_by(|a, b| {
                let a_latency = a.latency;
                let b_latency = b.latency;
                let priority_threshold = 50000u128;
                
                if a.is_private && !b.is_private {
                    if a_latency < b_latency.saturating_add(priority_threshold) {
                        std::cmp::Ordering::Less
                    } else {
                        std::cmp::Ordering::Greater
                    }
                } else if !a.is_private && b.is_private {
                    if b_latency < a_latency.saturating_add(priority_threshold) {
                        std::cmp::Ordering::Greater
                    } else {
                        std::cmp::Ordering::Less
                    }
                } else {
                    a_latency.cmp(&b_latency)
                }
            })
            .map(|n| n.url.clone())
    }

    pub fn get_fastest_pool(&self, limit: usize) -> Vec<String> {
        let mut sorted = self.nodes.clone();
        sorted.sort_by(|a, b| a.latency.cmp(&b.latency));
        sorted.iter()
            .filter(|n| n.fails < 3)
            .take(limit)
            .map(|n| n.url.clone())
            .collect()
    }

    pub fn update_latency(&mut self, url: &str, latency: u128) {
        if let Some(node) = self.nodes.iter_mut().find(|n| n.url == url) {
            node.latency = latency;
            node.fails = 0;
        }
    }

    pub fn mark_fail(&mut self, url: &str) {
        if let Some(node) = self.nodes.iter_mut().find(|n| n.url == url) {
            node.fails += 1;
        }
    }
}

pub static RPC_POOL: Lazy<Arc<RwLock<RpcPoolState>>> = Lazy::new(|| {
    Arc::new(RwLock::new(RpcPoolState::default()))
});

pub static SHUTDOWN_FLAG: Lazy<AtomicBool> = Lazy::new(|| AtomicBool::new(false));
