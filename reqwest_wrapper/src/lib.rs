use reqwest::{self, header::CONTENT_TYPE};
use pyo3::{prelude::*};
use pyo3::types::PyBytes;
use pyo3::{exceptions::PyRuntimeError, PyErr};

#[pyclass]
struct TTSClient {
    client: reqwest::blocking::Client,
}

enum TTSError {
    ReqwestErr(reqwest::Error),
    PyErr(PyErr),
    ServerErr(String),
}

impl From<reqwest::Error> for TTSError {
    fn from(value: reqwest::Error) -> Self {
        Self::ReqwestErr(value)
    }
}

impl From<PyErr> for TTSError {
    fn from(value: PyErr) -> Self {
        Self::PyErr(value)
    }
}

impl From<TTSError> for PyErr {
    fn from(err: TTSError) -> PyErr {
        match err {
            TTSError::ReqwestErr(e) => PyErr::new::<PyRuntimeError, _>(format!("Reqwest error: {}", e)),
            TTSError::PyErr(e) => e,
            TTSError::ServerErr(msg) => PyErr::new::<PyRuntimeError, _>(format!("Server error: {}", msg)),
        }
    }
}

#[pymethods]
impl TTSClient {
    #[new]
    fn new() -> Self {
        Self {
            client: reqwest::blocking::Client::new(),
        }
    }

    pub fn get_tts(&self, url: &str) -> PyResult<Py<PyAny>> {
        fn get_tts_helper(client: &reqwest::blocking::Client, url: &str) -> Result<Py<PyAny>, TTSError> {
            let res = client.get(url).send()?;
            if res.status().is_success() && res.headers().get(CONTENT_TYPE) == Some(&"audio/wav".parse().unwrap()) {
                let audio_data = res.bytes()?;
                let audio_data = std::borrow::Cow::Owned(audio_data.to_vec());
                Python::with_gil(|py| {
                    Ok(PyBytes::new(py, &audio_data).to_object(py))
                })
            } else {
                Err(TTSError::ServerErr(res.text()?))
            }
        }
        get_tts_helper(&self.client, url).map_err(From::from)
    }
}

/// A Python module implemented in Rust.
#[pymodule]
fn reqwest_wrapper(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<TTSClient>()?;
    Ok(())
}
