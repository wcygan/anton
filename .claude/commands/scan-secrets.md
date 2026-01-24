---
description: Scan codebase for exposed secrets and unencrypted sensitive data
---

Scan the codebase for exposed secrets that should not be committed to Git.

**This is a GitOps repository where ALL secrets must be SOPS-encrypted.**

## Scan Categories

### 1. Unencrypted SOPS Files
Check all `*.sops.yaml` and `*.sops.yml` files to verify they are properly encrypted:

```bash
# Find all SOPS files
find . -name "*.sops.yaml" -o -name "*.sops.yml" | grep -v node_modules

# For each file, check if it contains the SOPS metadata block
# Encrypted files MUST have: sops.age or sops.encrypted_regex sections
```

**Red flags:**
- `*.sops.*` files without `sops:` metadata block at the bottom
- `stringData:` or `data:` values that are NOT `ENC[AES256_GCM,...]`

### 2. High-Entropy Strings (Potential Secrets)
Search for patterns that indicate exposed secrets:

```bash
# API keys and tokens
rg -i "(api[_-]?key|api[_-]?token|auth[_-]?token|bearer|secret[_-]?key)" --type yaml --type json

# Base64 encoded secrets (longer than 20 chars, not in SOPS files)
rg "[A-Za-z0-9+/]{40,}={0,2}" --type yaml | grep -v "\.sops\." | grep -v "ENC\["

# AWS/Cloud credentials
rg -i "(aws[_-]?access|aws[_-]?secret|AKIA[A-Z0-9]{16})"

# Private keys
rg "PRIVATE KEY" --type yaml --type json
rg "BEGIN RSA"
rg "BEGIN EC"
rg "BEGIN OPENSSH"
```

### 3. Known Secret File Patterns
Check for files that should NEVER be committed:

```bash
# Files that should be in .gitignore
find . -name "*.pem" -o -name "*.key" -o -name "id_rsa*" -o -name "*.p12" -o -name "*.pfx" 2>/dev/null | grep -v ".gitignore"

# Environment files with secrets
find . -name ".env" -o -name ".env.*" -o -name "*.env" 2>/dev/null | head -20

# Credential files
find . -name "credentials*" -o -name "*password*" -o -name "*secret*" 2>/dev/null | grep -v ".sops." | grep -v ".md"
```

### 4. Kubernetes Secret Manifests
All Kubernetes Secrets MUST be SOPS-encrypted:

```bash
# Find Secret manifests that are NOT sops files
rg "kind: Secret" --type yaml -l | grep -v "\.sops\."
```

### 5. Hardcoded Passwords in HelmReleases
Check for inline passwords in HelmRelease values:

```bash
rg -i "(password|passwd|pwd):" kubernetes/ --type yaml | grep -v "passwordSecretRef" | grep -v "existingSecret"
```

### 6. Cloudflare/External Service Tokens
Check for exposed service credentials:

```bash
rg -i "(cloudflare|tunnel|CF_)" --type yaml | grep -v "secretKeyRef" | grep -v "\.sops\."
rg "tunnel:" kubernetes/ --type yaml -A5 | grep -i "secret\|token\|credential"
```

## Output Format

For each finding, report:

| Severity | File | Line | Issue | Recommendation |
|----------|------|------|-------|----------------|
| 🔴 Critical | path/to/file | 42 | Unencrypted API key | Encrypt with SOPS |
| 🟡 Warning | path/to/file | 15 | Hardcoded password | Use secretKeyRef |
| 🟢 Info | path/to/file | 8 | High-entropy string | Verify if sensitive |

## Severity Levels

- **🔴 Critical**: Confirmed exposed secret (API keys, passwords, tokens in plaintext)
- **🟡 Warning**: Potential secret or misconfiguration (hardcoded values that should use refs)
- **🟢 Info**: Suspicious pattern that needs manual review

## Expected Safe Patterns

These patterns are SAFE and should NOT be flagged:

```yaml
# Safe: References to secrets (not the secrets themselves)
secretKeyRef:
  name: my-secret
  key: password

# Safe: SOPS-encrypted values
password: ENC[AES256_GCM,data:xyz123,...]

# Safe: Flux variable substitution
token: ${SECRET_CLOUDFLARE_TOKEN}

# Safe: Helm value references
password: "{{ .Values.auth.password }}"
```

## Remediation Guide

If secrets are found:

1. **Immediately**: Do NOT commit. If already committed, consider the secret compromised.
2. **Rotate**: Generate new credentials for any exposed secrets.
3. **Encrypt**: Move secret to a `*.sops.yaml` file and encrypt:
   ```bash
   sops --encrypt --in-place path/to/secret.sops.yaml
   ```
4. **Reference**: Update manifests to use `secretKeyRef` or Flux substitution.
5. **Verify**: Run `task configure` to validate encryption.

## After Scanning

Provide:
1. **Summary**: Total files scanned, issues found by severity
2. **Findings table**: Detailed list of all issues
3. **Recommendations**: Prioritized remediation steps
4. **Verification command**: How to re-scan after fixes
