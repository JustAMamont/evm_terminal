use std::io::Write;
use std::sync::Mutex;
use crossbeam_channel::{unbounded, Receiver, Sender};
use once_cell::sync::Lazy;

// Signal socket for notifying Python
static SIGNAL_TX: Lazy<Mutex<Option<std::net::TcpStream>>> = Lazy::new(|| Mutex::new(None));

// JSON queue for fallback (when Ring Buffer is full)
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
    *SIGNAL_TX.lock().unwrap() = Some(stream);
    Ok(())
}

/// Signal Python that data is available
pub fn signal_python() {
    if let Some(mut sock) = SIGNAL_TX.lock().unwrap().take() {
        let _ = sock.write(b"\x00");
        *SIGNAL_TX.lock().unwrap() = Some(sock);
    }
}

/// Send JSON to Python (fallback when Ring Buffer is full)
pub fn send_to_python(json: String) {
    let _ = BRIDGE_QUEUE.0.send(json);
    signal_python();
}