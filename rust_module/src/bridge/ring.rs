use std::sync::atomic::{AtomicU64, Ordering};
use std::cell::UnsafeCell;

// === CONSTANTS ===
pub const EVENT_RING_SIZE: usize = 2048;
pub const MAX_MSG_SIZE: usize = 4096;
pub const SLOT_OVERHEAD: usize = 8;  // [len:4][checksum:4]
pub const SLOT_SIZE: usize = MAX_MSG_SIZE + SLOT_OVERHEAD;

/// Lock-free Single Producer Single Consumer Ring Buffer
pub struct RingBuffer {
    write_idx: AtomicU64,
    read_idx: AtomicU64,
    _pad: [u8; 48],  // Cache line padding
    slots: Vec<UnsafeCell<[u8; SLOT_SIZE]>>,  // Vec вместо Box<[..; N]>
}

unsafe impl Send for RingBuffer {}
unsafe impl Sync for RingBuffer {}

impl RingBuffer {
    pub fn new() -> Self {
        // Vec аллоцирует сразу в куче, без стека
        let slots = (0..EVENT_RING_SIZE)
            .map(|_| UnsafeCell::new([0u8; SLOT_SIZE]))
            .collect();
        
        Self {
            write_idx: AtomicU64::new(0),
            read_idx: AtomicU64::new(0),
            _pad: [0; 48],
            slots,
        }
    }
    
    #[inline]
    pub fn len(&self) -> usize {
        let read = self.read_idx.load(Ordering::Acquire);
        let write = self.write_idx.load(Ordering::Acquire);
        (write.saturating_sub(read)) as usize
    }
    
    /// Producer: write message
    #[inline]
    pub fn push(&self, data: &[u8]) -> Result<(), ()> {
        let len = data.len();
        if len > MAX_MSG_SIZE {
            return Err(());
        }
        
        let write = self.write_idx.load(Ordering::Relaxed);
        let read = self.read_idx.load(Ordering::Acquire);
        
        if write - read >= EVENT_RING_SIZE as u64 {
            return Err(()); // Buffer full
        }
        
        let slot_idx = (write & (EVENT_RING_SIZE - 1) as u64) as usize;
        let slot = unsafe { &mut *self.slots[slot_idx].get() };
        
        // [len:4][checksum:4][payload:len]
        let checksum = crc32(data);
        slot[0..4].copy_from_slice(&(len as u32).to_le_bytes());
        slot[4..8].copy_from_slice(&checksum.to_le_bytes());
        slot[8..8+len].copy_from_slice(data);
        
        std::sync::atomic::fence(Ordering::Release);
        self.write_idx.store(write + 1, Ordering::Release);
        
        Ok(())
    }
    
    /// Consumer: read message
    #[inline]
    pub fn pop(&self) -> Option<Vec<u8>> {
        let read = self.read_idx.load(Ordering::Relaxed);
        let write = self.write_idx.load(Ordering::Acquire);
        
        if read >= write {
            return None;
        }
        
        let slot_idx = (read & (EVENT_RING_SIZE - 1) as u64) as usize;
        let slot = unsafe { &*self.slots[slot_idx].get() };
        
        let len = u32::from_le_bytes([slot[0], slot[1], slot[2], slot[3]]) as usize;
        let stored_checksum = u32::from_le_bytes([slot[4], slot[5], slot[6], slot[7]]);
        
        if len > MAX_MSG_SIZE {
            self.read_idx.store(read + 1, Ordering::Release);
            return None;
        }
        
        let data = slot[8..8+len].to_vec();
        let computed_checksum = crc32(&data);
        
        if computed_checksum != stored_checksum {
            self.read_idx.store(read + 1, Ordering::Release);
            return None;
        }
        
        self.read_idx.store(read + 1, Ordering::Release);
        Some(data)
    }
}

/// CRC32 checksum (IEEE polynomial)
fn crc32(data: &[u8]) -> u32 {
    let mut crc: u32 = 0xFFFFFFFF;
    for &byte in data {
        crc ^= byte as u32;
        for _ in 0..8 {
            if crc & 1 != 0 {
                crc = (crc >> 1) ^ 0xEDB88320;
            } else {
                crc >>= 1;
            }
        }
    }
    !crc
}

impl Default for RingBuffer {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_push_pop_single() {
        let ring = RingBuffer::new();
        let data = b"hello world";
        
        assert!(ring.push(data).is_ok());
        let result = ring.pop();
        
        assert!(result.is_some());
        assert_eq!(result.unwrap(), data.to_vec());
    }
    
    #[test]
    fn test_fifo_order() {
        let ring = RingBuffer::new();
        
        for i in 0..10u8 {
            ring.push(&[i]).unwrap();
        }
        
        for i in 0..10u8 {
            let result = ring.pop().unwrap();
            assert_eq!(result[0], i);
        }
    }
    
    #[test]
    fn test_buffer_full() {
        let ring = RingBuffer::new();
        
        for i in 0..EVENT_RING_SIZE {
            assert!(ring.push(&[i as u8]).is_ok());
        }
        
        assert!(ring.push(b"overflow").is_err());
    }
    
    #[test]
    fn test_empty_pop() {
        let ring = RingBuffer::new();
        assert!(ring.pop().is_none());
    }
    
    #[test]
    fn test_len() {
        let ring = RingBuffer::new();
        assert_eq!(ring.len(), 0);
        
        ring.push(b"test").unwrap();
        assert_eq!(ring.len(), 1);
        
        ring.push(b"test2").unwrap();
        assert_eq!(ring.len(), 2);
        
        ring.pop().unwrap();
        assert_eq!(ring.len(), 1);
    }
    
    #[test]
    fn test_crc_validation() {
        let ring = RingBuffer::new();
        let data = b"test data";
        
        ring.push(data).unwrap();
        let result = ring.pop().unwrap();
        assert_eq!(result, data.to_vec());
    }
    
    #[test]
    fn test_max_size_message() {
        let ring = RingBuffer::new();
        let data = vec![0xABu8; MAX_MSG_SIZE];
        
        assert!(ring.push(&data).is_ok());
        let result = ring.pop().unwrap();
        assert_eq!(result.len(), MAX_MSG_SIZE);
    }
    
    #[test]
    fn test_oversized_message() {
        let ring = RingBuffer::new();
        let data = vec![0u8; MAX_MSG_SIZE + 1];
        
        assert!(ring.push(&data).is_err());
    }
}