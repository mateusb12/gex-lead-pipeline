from source.shared.config import Settings


def test_settings_is_debug_env_retorna_true_para_ambientes_de_debug():
    assert Settings(app_env="local").is_debug_env is True
    assert Settings(app_env="dev").is_debug_env is True
    assert Settings(app_env="debug").is_debug_env is True


def test_settings_is_debug_env_retorna_false_para_production():
    assert Settings(app_env="production").is_debug_env is False
