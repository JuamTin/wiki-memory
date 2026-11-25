import re


class SecretRedactor:
    patterns = (
        ("PEM", re.compile(r"-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----.*?(?:-----END \1-----|\Z)", re.S)),
        ("BEARER", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I)),
        ("JWT", re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+")),
        ("OPENAI", re.compile(r"\bsk-[\w-]+")),
        ("GITHUB", re.compile(r"\b(?:ghp_|github_pat_)[\w]+")),
        ("ASSIGNMENT", re.compile(r"""(?ix)\b[\w.-]*(?:API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*(?:"[^"\n]*"|'[^'\n]*'|[^\s,;]+)""")),
    )

    @classmethod
    def redact(cls, text: str) -> str:
        for label, pattern in cls.patterns:
            text = pattern.sub(f"[REDACTED:{label}]", text)
        return text
