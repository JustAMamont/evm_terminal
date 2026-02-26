use pyo3::prelude::*;

mod state;
mod bridge;
mod engine;
mod monitor;
mod execution;
mod crypto;
mod pnl;
mod config;

#[pymodule]
fn dexbot_core(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(bridge::init_bridge_signal, m)?)?;
    m.add_function(wrap_pyfunction!(bridge::pop_from_bridge, m)?)?;
    m.add_function(wrap_pyfunction!(engine::push_to_engine, m)?)?;
    m.add_function(wrap_pyfunction!(crypto::init_or_load_keys, m)?)?;
    m.add_function(wrap_pyfunction!(crypto::get_public_key, m)?)?; 
    m.add_function(wrap_pyfunction!(config::get_network_config, m)?)?;
    m.add_function(wrap_pyfunction!(config::get_available_networks, m)?)?;
    Ok(())
}
