from loguru import logger

with logger.catch():
    from typing import Dict, Any, Literal, Tuple
    from dataclasses import dataclass
    import os
    import json


Json = Dict[str, Any]


@dataclass
class HotKey:
    key_type: Literal["keyboard", "mouse", "null"]
    key_name: str

    def to_json(self) -> Json:
        return {
            "key_type": self.key_type,
            "key_name": self.key_name
        }

    @classmethod
    def from_json(cls, json: Json) -> "HotKey":  # I forgot to switch to py3.11 before developing this...
        key_type = json["key_type"]
        key_name = json["key_name"]
        return HotKey(key_type, key_name)

    @classmethod
    def default(cls) -> "HotKey":
        return HotKey("mouse", "middle")


@dataclass
class Config:
    tts_api_url: str
    capture_window_pos: Tuple[int, int]
    capture_window_size: Tuple[int, int]
    hot_key: HotKey

    def to_json(self) -> Json:
        return {
            "tts_api_url": self.tts_api_url,
            "capture_window_pos": self.capture_window_pos,
            "capture_window_size": self.capture_window_size,
            "hot_key": self.hot_key.to_json()
        }
    
    @classmethod
    def from_json(cls, json: Json) -> "Config":
        tts_api_url = json["tts_api_url"]
        capture_window_pos = json["capture_window_pos"]
        capture_window_size = json["capture_window_size"]
        hot_key = HotKey.from_json(json["hot_key"])
        return Config(tts_api_url, capture_window_pos, capture_window_size, hot_key)

    @classmethod
    def default(cls) -> "Config":
        return Config(
            tts_api_url="http://localhost:47867/tts?format=wav&text=%s",
            capture_window_pos=(200, 200),
            capture_window_size=(600, 200),
            hot_key=HotKey.default()
        )


def load_config(config_path: str) -> Config:
    # if config file not exists, create a new one... I start missing Default trait in Rust...
    if os.path.exists(config_path):
        logger.info("Config file found, loading...")
        with open(config_path, "r") as f:
            return Config.from_json(json.load(f))
    else:
        logger.info("Config file not found, creating a new one with default settings...")
        return Config.default()


def save_config(config_path: str, config: Config) -> None:
    with open(config_path, "w") as f:
        json.dump(config.to_json(), f)