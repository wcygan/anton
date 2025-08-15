# Dependency Management for Cluster Template

## Overview

This cluster template uses [mise](https://mise.jdx.dev/) (formerly rtx) for managing development dependencies and CLI tools required for cluster operations.

## Installing Dependencies

When setting up the cluster template for the first time or on a new machine, you can install all required dependencies with a single command:

```bash
mise install
```

This command will automatically install all the tools defined in the `.mise.toml` configuration file, including:

- **cue** (`aqua:cue-lang/cue@0.13.1`) - Configuration language for defining and validating data
- **kubeconform** (`aqua:yannh/kubeconform@0.7.0`) - Kubernetes manifest validation tool
- **yq** (`aqua:mikefarah/yq@4.45.4`) - YAML processor and query tool
- **gh** (`aqua:cli/cli@2.74.1`) - GitHub CLI for repository operations
- **cilium-cli** (`aqua:cilium/cilium-cli@0.18.4`) - CLI for managing Cilium CNI

## Benefits of Using mise

1. **Reproducible Environments**: All developers and CI/CD pipelines use the exact same tool versions
2. **No Manual Installation**: No need to manually install each tool or manage versions
3. **Cross-Platform**: Works consistently across macOS, Linux, and WSL
4. **Version Pinning**: Tools are pinned to specific versions for stability
5. **Aqua Integration**: Uses the Aqua package registry for fast, reliable tool downloads

## Verifying Installation

After running `mise install`, you can verify the tools are installed:

```bash
# Check installed tools
mise list

# Verify specific tool versions
cue version
kubeconform -v
yq --version
gh --version
cilium version --client
```

## Troubleshooting

If you encounter issues during installation:

1. **Update mise**: Ensure you have the latest version
   ```bash
   mise self-update
   ```

2. **Clear cache**: If downloads fail, clear the mise cache
   ```bash
   mise cache clear
   ```

3. **Check prerequisites**: Some tools may require system dependencies
   - Ensure you have a working internet connection
   - Check if you need to configure proxy settings
   - Verify you have sufficient disk space

4. **Manual fallback**: If a specific tool fails to install via mise, you can install it manually and mise will detect it

## Adding New Dependencies

To add new tools to the project:

1. Edit `.mise.toml` and add the tool specification
2. Run `mise install` to install the new tool
3. Commit the updated `.mise.toml` to ensure all team members get the new dependency

## Related Documentation

- [Initial Setup Guide](../../README.md#stage-2-local-workstation) - See Stage 2 for complete workstation setup
- [mise Documentation](https://mise.jdx.dev/) - Official mise documentation
- [Aqua Registry](https://github.com/aquaproj/aqua-registry) - Browse available tools