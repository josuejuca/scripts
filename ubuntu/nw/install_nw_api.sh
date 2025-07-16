#!/bin/bash

# Baixar o arquivo do GitHub 
curl -o /tmp/nw-api.service scripts.josuejuca.com/ubuntu/nw/nw-api.service

# Mover para o diretório do systemd
sudo mv /tmp/nw-api.service /etc/systemd/system/nw-api.service

# Dar permissão se necessário
sudo chmod 644 /etc/systemd/system/nw-api.service

# Recarregar systemd
sudo systemctl daemon-reload

# Habilitar e iniciar serviço
sudo systemctl enable nw-api
sudo systemctl start nw-api

echo "Serviço nw-api instalado e iniciado!"
