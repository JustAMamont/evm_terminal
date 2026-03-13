use std::io::Write;
use parking_lot::Mutex;
use crossbeam_channel::{unbounded, Receiver, Sender};
use once_cell::sync::Lazy;

static SIGNAL_TX: Lazy<Mutex<Option<std::net::TcpStream>>> = Lazy::new(|| Mutex::new(None));
pub static BRIDGE_QUEUE: Lazy<(Sender<String>, Receiver<String>)> = Lazy::new(|| unbounded());

pub fn set_signal_socket(fd: u64) -> Result<(), String> {
    #[cfg(unix)]
    use std::os::unix::io::FromRawFd;
    #[cfg(windows)]
    use std::os::windows::io::FromRawSocket;
    
    let stream = unsafe {
        #[cfg(unix)] { std::net::TcpStream::from_raw_fd(fd as i32) }
        #[cfg(windows)] { std::net::TcpStream::from_raw_socket(fd) }
    };
    stream.set_nonblocking(true).map_err(|e| e.to_string())?;
    *SIGNAL_TX.lock() = Some(stream);
    Ok(())
}

pub fn signal_python() {
    let mut guard = SIGNAL_TX.lock();
    if let Some(ref mut sock) = guard.as_mut() {
        let _ = sock.write(b"\x00");
    }
}

pub fn send_to_python(json: String) {
    let _ = BRIDGE_QUEUE.0.send(json);
    signal_python();
}