"""SignalVault settings package.

C1-A: AppPaths — unified, platform-aware application paths.
C1-B: ConfigSchema, ConfigService, SecretStore — configuration subsystem.
C1-C: LLMRuntimeConfig, SetupStatus, LLM Validator, Obsidian Validator,
      Vault Manifest — runtime configuration and validation services.

Do NOT place modules under src/signalvault/config/ — that would collide
with the existing config.py compatibility facade.
"""
