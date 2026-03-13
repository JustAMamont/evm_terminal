// === EVENT TYPE REGISTRY ===
#[repr(u16)]
pub enum EventType {
    EngineReady      = 0x0000,
    Log              = 0x0001,
    ConnectionStatus = 0x0002,
    GasPriceUpdate   = 0x0003,
    BalanceUpdate    = 0x0100,
    PoolDetected     = 0x0200,
    PoolUpdate       = 0x0201,
    PoolNotFound     = 0x0202,
    ImpactUpdate     = 0x0203,
    TxSent           = 0x0300,
    TxConfirmed      = 0x0301,
    TradeStatus      = 0x0302,
    AutoFuelError    = 0x0303,
    PnLUpdate        = 0x0400,
}

// === COMMAND TYPE REGISTRY ===
#[repr(u16)]
pub enum CommandType {
    Init                = 0x0000,
    Shutdown            = 0x0001,
    SwitchToken         = 0x0100,
    UnsubscribeToken    = 0x0101,
    ExecuteTrade        = 0x0200,
    CalcImpact          = 0x0201,
    UpdatePrice         = 0x0300,
    UpdateSettings      = 0x0301,
    UpdateTokenDecimals = 0x0302,
    RefreshBalance      = 0x0303,
    AddWallet           = 0x0304,
    RefreshAllBalances  = 0x0305,
}

// === PACK TRAIT ===
pub trait Packable: Sized {
    fn pack(&self, writer: &mut Vec<u8>);
    fn unpack(reader: &mut &[u8]) -> Result<Self, PackError>;
}

#[derive(Debug)]
pub enum PackError {
    UnexpectedEnd,
    InvalidData,
}

// === PACK HELPERS ===

#[inline]
pub fn pack_u8(w: &mut Vec<u8>, v: u8) {
    w.push(v);
}

#[inline]
pub fn pack_u16(w: &mut Vec<u8>, v: u16) {
    w.extend_from_slice(&v.to_le_bytes());
}

#[inline]
pub fn pack_u32(w: &mut Vec<u8>, v: u32) {
    w.extend_from_slice(&v.to_le_bytes());
}

#[inline]
pub fn pack_u64(w: &mut Vec<u8>, v: u64) {
    w.extend_from_slice(&v.to_le_bytes());
}

#[inline]
pub fn pack_f64(w: &mut Vec<u8>, v: f64) {
    w.extend_from_slice(&v.to_le_bytes());
}

#[inline]
pub fn pack_bool(w: &mut Vec<u8>, v: bool) {
    w.push(if v { 1 } else { 0 });
}

#[inline]
pub fn pack_string(w: &mut Vec<u8>, s: &str) {
    let bytes = s.as_bytes();
    pack_u16(w, bytes.len() as u16);
    w.extend_from_slice(bytes);
}

// === UNPACK HELPERS ===

#[inline]
pub fn unpack_u8(r: &mut &[u8]) -> Result<u8, PackError> {
    if r.is_empty() { return Err(PackError::UnexpectedEnd); }
    let v = r[0];
    *r = &r[1..];
    Ok(v)
}

#[inline]
pub fn unpack_u16(r: &mut &[u8]) -> Result<u16, PackError> {
    if r.len() < 2 { return Err(PackError::UnexpectedEnd); }
    let v = u16::from_le_bytes([r[0], r[1]]);
    *r = &r[2..];
    Ok(v)
}

#[inline]
pub fn unpack_u32(r: &mut &[u8]) -> Result<u32, PackError> {
    if r.len() < 4 { return Err(PackError::UnexpectedEnd); }
    let v = u32::from_le_bytes([r[0], r[1], r[2], r[3]]);
    *r = &r[4..];
    Ok(v)
}

#[inline]
pub fn unpack_u64(r: &mut &[u8]) -> Result<u64, PackError> {
    if r.len() < 8 { return Err(PackError::UnexpectedEnd); }
    let v = u64::from_le_bytes([r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]]);
    *r = &r[8..];
    Ok(v)
}

#[inline]
pub fn unpack_f64(r: &mut &[u8]) -> Result<f64, PackError> {
    if r.len() < 8 { return Err(PackError::UnexpectedEnd); }
    let v = f64::from_le_bytes([r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]]);
    *r = &r[8..];
    Ok(v)
}

#[inline]
pub fn unpack_bool(r: &mut &[u8]) -> Result<bool, PackError> {
    Ok(unpack_u8(r)? != 0)
}

#[inline]
pub fn unpack_string(r: &mut &[u8]) -> Result<String, PackError> {
    let len = unpack_u16(r)? as usize;
    if r.len() < len { return Err(PackError::UnexpectedEnd); }
    let s = String::from_utf8_lossy(&r[..len]).into_owned();
    *r = &r[len..];
    Ok(s)
}


// ================ TESTS ==============

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_pack_u8() {
        let mut w = Vec::new();
        pack_u8(&mut w, 0x42);
        assert_eq!(w, vec![0x42]);
    }
    
    #[test]
    fn test_pack_u16() {
        let mut w = Vec::new();
        pack_u16(&mut w, 0x1234);
        assert_eq!(w, vec![0x34, 0x12]); // little endian
    }
    
    #[test]
    fn test_pack_u32() {
        let mut w = Vec::new();
        pack_u32(&mut w, 0x12345678);
        assert_eq!(w, vec![0x78, 0x56, 0x34, 0x12]);
    }
    
    #[test]
    fn test_pack_u64() {
        let mut w = Vec::new();
        pack_u64(&mut w, 0x123456789ABCDEF0);
        assert_eq!(w, vec![0xF0, 0xDE, 0xBC, 0x9A, 0x78, 0x56, 0x34, 0x12]);
    }
    
    #[test]
    fn test_pack_f64() {
        let mut w = Vec::new();
        pack_f64(&mut w, 3.14159);
        assert_eq!(w.len(), 8);
    }
    
    #[test]
    fn test_pack_bool() {
        let mut w = Vec::new();
        pack_bool(&mut w, true);
        pack_bool(&mut w, false);
        assert_eq!(w, vec![1, 0]);
    }
    
    #[test]
    fn test_pack_string() {
        let mut w = Vec::new();
        pack_string(&mut w, "hello");
        assert_eq!(w, vec![5, 0, b'h', b'e', b'l', b'l', b'o']);
    }
    
    #[test]
    fn test_unpack_u8() {
        let mut r: &[u8] = &[0x42];
        assert_eq!(unpack_u8(&mut r).unwrap(), 0x42);
        assert!(r.is_empty());
    }
    
    #[test]
    fn test_unpack_u16() {
        let mut r: &[u8] = &[0x34, 0x12];
        assert_eq!(unpack_u16(&mut r).unwrap(), 0x1234);
    }
    
    #[test]
    fn test_unpack_u32() {
        let mut r: &[u8] = &[0x78, 0x56, 0x34, 0x12];
        assert_eq!(unpack_u32(&mut r).unwrap(), 0x12345678);
    }
    
    #[test]
    fn test_unpack_string() {
        let mut r: &[u8] = &[5, 0, b'h', b'e', b'l', b'l', b'o'];
        assert_eq!(unpack_string(&mut r).unwrap(), "hello");
    }
    
    #[test]
    fn test_unpack_unexpected_end() {
        let mut r: &[u8] = &[0x01];
        assert!(matches!(unpack_u16(&mut r), Err(PackError::UnexpectedEnd)));
    }
    
    #[test]
    fn test_roundtrip_u64() {
        let mut w = Vec::new();
        let val = 0xDEADBEEFCAFEBABEu64;
        pack_u64(&mut w, val);
        
        let mut r: &[u8] = &w;
        assert_eq!(unpack_u64(&mut r).unwrap(), val);
    }
    
    #[test]
    fn test_roundtrip_string() {
        let mut w = Vec::new();
        let s = "test string with unicode: 你好";
        pack_string(&mut w, s);
        
        let mut r: &[u8] = &w;
        assert_eq!(unpack_string(&mut r).unwrap(), s);
    }
}