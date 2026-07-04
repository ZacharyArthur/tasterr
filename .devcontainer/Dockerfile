FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

# uv and just into /usr/local/bin (root-installed, on PATH for every user)
RUN curl -LsSf https://astral.sh/uv/install.sh \
        | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh \
    && curl -LsSf https://just.systems/install.sh | bash -s -- --to /usr/local/bin
