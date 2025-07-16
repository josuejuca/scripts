# Instalar Serviço NW API (FastAPI) no Ubuntu

## 1. Baixe o script de instalação
Use o comando abaixo para baixar diretamente 

```bash
curl -O scripts.josuejuca.com/ubuntu/nw/install_nw_api.sh
```

ou, se preferir usar wget

```bash
wget scripts.josuejuca.com/ubuntu/nw/install_nw_api.sh
```


## 2. Dê permissão de execução ao script

```bash
chmod +x install_nw_api.sh
```

## 3. Execute o script

```bash
./install_nw_api.sh
```

## 4. Verifique o status do serviço

```bash
sudo systemctl status nw-api
```

Se aparecer active (running), é que deu certo 
