use pyo3::prelude::*;
use ed25519_dalek::{SigningKey, VerifyingKey};
use pkcs8::{EncodePublicKey, LineEnding};
use once_cell::sync::Lazy;
use std::sync::RwLock;
use std::path::PathBuf;
use std::fs;
use aes_gcm::{Aes256Gcm, Key, Nonce};
use aes_gcm::aead::{Aead, KeyInit, AeadCore};
use pbkdf2::pbkdf2_hmac;
use sha2::Sha256;
use rand::RngCore;
use rand::rngs::OsRng;
use typenum::Unsigned;


// Глобальная переменная для хранения приватного ключа в оперативной памяти
static BOT_KEYPAIR: Lazy<RwLock<Option<SigningKey>>> = Lazy::new(|| RwLock::new(None));

const SALT_SIZE: usize = 16;
const NONCE_SIZE: usize = <Aes256Gcm as AeadCore>::NonceSize::USIZE;

/// Выводит 32-байтный ключ из пароля и соли
fn derive_key_from_password(password: &str, salt: &[u8]) -> Key<Aes256Gcm> {
    let mut key = [0u8; 32];
    pbkdf2_hmac::<Sha256>(password.as_bytes(), salt, 480_000, &mut key);
    key.into()
}

#[pyfunction]
/// Инициализирует или загружает ключ из зашифрованного файла.
pub fn init_or_load_keys(key_path_str: String, master_password: &str) -> PyResult<()> {
    let key_path = PathBuf::from(key_path_str);
    let mut keypair_guard = BOT_KEYPAIR.write().unwrap();

    if key_path.exists() {
        let file_content = fs::read(&key_path)?;
        if file_content.len() < SALT_SIZE + NONCE_SIZE {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>("Invalid key file format"));
        }
        
        let (salt, rest) = file_content.split_at(SALT_SIZE);
        let (nonce_bytes, encrypted_key) = rest.split_at(NONCE_SIZE);
        
        let key = derive_key_from_password(master_password, salt);
        let cipher = Aes256Gcm::new(&key);
        
        // Создаем пустой Nonce и копируем в него данные из среза
        let mut nonce = Nonce::default();
        nonce.copy_from_slice(nonce_bytes);

        // Передаем ссылку &nonce, так как метод decrypt ожидает именно ее
        let decrypted_key_bytes = cipher.decrypt(&nonce, encrypted_key)
            .map_err(|_| PyErr::new::<pyo3::exceptions::PyValueError, _>("Decryption failed. Wrong master password?"))?;

        let signing_key = SigningKey::from_bytes(
            &decrypted_key_bytes.try_into().map_err(|_| PyErr::new::<pyo3::exceptions::PyValueError, _>("Invalid key data after decryption"))?
        );
        *keypair_guard = Some(signing_key);

    } else {
        let mut csprng = OsRng;
        let signing_key = SigningKey::generate(&mut csprng);
        
        let mut salt = [0u8; SALT_SIZE];
        csprng.fill_bytes(&mut salt);
        
        let key = derive_key_from_password(master_password, &salt);
        let cipher = Aes256Gcm::new(&key);
        
        let nonce = Aes256Gcm::generate_nonce(&mut csprng);

        let encrypted_key = cipher.encrypt(&nonce, signing_key.to_bytes().as_ref())
            .map_err(|_| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Encryption failed"))?;
        
        if let Some(parent_dir) = key_path.parent() {
            fs::create_dir_all(parent_dir)?;
        }

        let mut file_content = Vec::new();
        file_content.extend_from_slice(&salt);
        file_content.extend_from_slice(&nonce);
        file_content.extend_from_slice(&encrypted_key);
        
        fs::write(&key_path, file_content)?;
        
        *keypair_guard = Some(signing_key);
    }
    Ok(())
}

#[pyfunction]
pub fn get_public_key() -> PyResult<String> {
    let keypair_guard = BOT_KEYPAIR.read().unwrap();
    if let Some(key) = &*keypair_guard {
        let public_key: VerifyingKey = (&*key).into();
        Ok(public_key.to_public_key_pem(LineEnding::LF)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("PEM encoding failed: {}", e)))?
        )
    } else {
        Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Keys not initialized."))
    }
}