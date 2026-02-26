use pyo3::prelude::*;
use pyo3::types::PyDict;
use pyo3::exceptions::{PyValueError, PyFileNotFoundError};
use serde::Deserialize;
use std::fs;
use std::path::Path;
use std::collections::HashMap;

#[derive(Deserialize, Debug)]
pub struct NetworkConfig {
    pub name: String,
    pub db_path: String,
    pub chain_id: u64,
    pub rpc_url: String,
    pub native_currency_symbol: String,
    pub native_currency_address: String,
    pub explorer_url: String,
    pub dex_router_address: String,
    pub v2_factory_address: Option<String>,
    pub v3_factory_address: Option<String>,
    pub v2_router_address: Option<String>,
    pub v3_quoter_address: Option<String>,
    pub public_rpc_urls: Option<Vec<String>>,
    pub fee_receiver: Option<String>,
    pub default_quote_currency: String,
    pub quote_tokens: HashMap<String, String>,
}

#[pyfunction]
pub fn get_available_networks(_py: Python<'_>) -> PyResult<Vec<String>> {
    let path = Path::new("networks");
    if !path.exists() {
        return Ok(Vec::new());
    }

    let mut networks = Vec::new();
    let entries = fs::read_dir(path)?;

    for entry in entries {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) == Some("json") {
            if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                networks.push(stem.to_string());
            }
        }
    }
    
    // Сортировка для предсказуемости
    networks.sort();
    Ok(networks)
}

#[pyfunction]
pub fn get_network_config(py: Python<'_>, network_name: String) -> PyResult<PyObject> {
    let filename = format!("networks/{}.json", network_name);
    let path = Path::new(&filename);

    if !path.exists() {
        return Err(PyFileNotFoundError::new_err(format!("Network config not found: {}", filename)));
    }

    let file_content = fs::read_to_string(path)
        .map_err(|e| PyValueError::new_err(format!("Failed to read config file: {}", e)))?;

    let config: NetworkConfig = serde_json::from_str(&file_content)
        .map_err(|e| PyValueError::new_err(format!("Invalid JSON format: {}", e)))?;

    let dict = PyDict::new(py);

    dict.set_item("name", config.name)?;
    dict.set_item("db_path", config.db_path)?;
    dict.set_item("chain_id", config.chain_id)?;
    dict.set_item("rpc_url", config.rpc_url)?;
    dict.set_item("native_currency_symbol", config.native_currency_symbol)?;
    dict.set_item("native_currency_address", config.native_currency_address)?;
    dict.set_item("explorer_url", config.explorer_url)?;
    dict.set_item("dex_router_address", config.dex_router_address)?;
    dict.set_item("default_quote_currency", config.default_quote_currency)?;

    if let Some(v) = config.v2_factory_address { dict.set_item("v2_factory_address", v)?; }
    if let Some(v) = config.v3_factory_address { dict.set_item("v3_factory_address", v)?; }
    if let Some(v) = config.v2_router_address { dict.set_item("v2_router_address", v)?; }
    if let Some(v) = config.v3_quoter_address { dict.set_item("v3_quoter_address", v)?; }
    if let Some(v) = config.public_rpc_urls { dict.set_item("public_rpc_urls", v)?; }
    if let Some(v) = config.fee_receiver { dict.set_item("fee_receiver", v)?; }

    let quote_tokens_dict = PyDict::new(py);
    for (key, value) in config.quote_tokens {
        quote_tokens_dict.set_item(key, value)?;
    }
    dict.set_item("quote_tokens", quote_tokens_dict)?;

    Ok(dict.to_object(py))
}
