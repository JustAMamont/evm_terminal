use std::io::Write;
use std::net::TcpStream;
use std::sync::Mutex;
use crossbeam_channel::{unbounded, Receiver, Sender};
use once_cell::sync::Lazy;

pub static BRIDGE_QUEUE: Lazy<(Sender<String>, Receiver<String>)> = Lazy::new(unbounded);
pub static SIGNAL_TX: Lazy<Mutex<Option<TcpStream>>> = Lazy::new(|| Mutex::new(None));

pub fn send_to_python(json: String) {
    let _ = BRIDGE_QUEUE.0.send(json);
    let mut guard = SIGNAL_TX.lock().unwrap();
    if let Some(ref mut stream) = *guard {
        let _ = stream.write(&[1]);
    }
}

pub fn set_signal_socket(fd: u64) -> Result<(), String> {
    let stream = unsafe {
        #[cfg(unix)] { use std::os::unix::io::FromRawFd; TcpStream::from_raw_fd(fd as i32) }
        #[cfg(windows)] { use std::os::windows::io::FromRawSocket; TcpStream::from_raw_socket(fd) }
    };
    stream.set_nonblocking(true).map_err(|e| e.to_string())?;
    *SIGNAL_TX.lock().unwrap() = Some(stream);
    Ok(())
}
