# Instalar OCTOPUS en un NAS, Unraid, Portainer o Proxmox

OCTOPUS se puede instalar en el aparato que ya tengas en la oficina. No hay que compilar nada: se descarga ya
hecho. Lo único que tienes que saber es **la IP de tu NAS o servidor** (por ejemplo `192.168.1.20`). La ves en la
web de tu NAS (Panel de control > Red) o en el router.

Cuando termines, abre en el navegador **`https://IP-de-tu-NAS:8443`**.

- El navegador avisará de que «la conexión no es privada». Es normal, porque OCTOPUS usa su propio certificado.
  Pulsa *Avanzado* y luego *Continuar*.
- Usuario: **admin**.
- La primera contraseña está en el **Registro** (o «Log») del contenedor, dentro de la web de tu NAS. Sirve una
  sola vez: el panel te pedirá una nueva y después ya no vuelve a salir.

> **Qué NAS sirven:** cualquiera con Docker y procesador Intel/AMD o ARM de 64 bits. Eso incluye casi todos los
> Synology «+» y los QNAP de los últimos años. Los NAS muy baratos con ARM de 32 bits no sirven.
> Recomendado: 2 GB de RAM libres.

---

## Synology (Container Manager)

1. Abre el **Centro de paquetes**, busca **Container Manager** e instálalo.
2. Abre **File Station** y crea la carpeta `docker/octopus`.
3. Abre **Container Manager**, ve a **Proyecto** y pulsa **Crear**.
   - Nombre del proyecto: `octopus`.
   - Ruta: la carpeta `docker/octopus` que acabas de crear.
   - Origen: **Crear docker-compose.yml**.
4. Pega el contenido de [`install/nas/docker-compose.yml`](install/nas/docker-compose.yml). En la línea
   `OCTOPUS_IP=192.168.1.20`, pon la IP de tu Synology.
5. Pulsa **Siguiente** y luego **Hecho**. Espera 1 o 2 minutos.
6. La contraseña está en **Contenedor** > **octopus** > **Registro**.

## QNAP (Container Station)

1. Abre el **App Center** e instala **Container Station**.
2. Abre Container Station, ve a **Aplicaciones** y pulsa **Crear**.
3. Nombre: `octopus`. Pega el contenido de [`install/nas/docker-compose.yml`](install/nas/docker-compose.yml)
   y cambia la IP.
4. Pulsa **Crear**. La contraseña está en **Contenedores** > **octopus** > **Registros**.

> El QNAP ya usa el puerto 8080 para su propia web. Por eso OCTOPUS usa el **8443** y el **8444**.

## Unraid

1. Copia [`install/unraid/octopus.xml`](install/unraid/octopus.xml) en la memoria USB de Unraid, en la carpeta
   `config/plugins/dockerMan/templates-user/`. También puedes hacerlo desde la consola:
   `wget -O /boot/config/plugins/dockerMan/templates-user/my-octopus.xml https://raw.githubusercontent.com/josemurajo/OCTOPUS/main/install/unraid/octopus.xml`
2. Ve a **Docker** > **Add Container** y elige **octopus** en *Template*.
3. Rellena **IP del servidor** con la IP de tu Unraid y pulsa **Apply**.
4. Para ver la contraseña, pulsa el icono de octopus y luego **Logs**.

## Portainer, CasaOS, TrueNAS SCALE, Dockge…

Todos permiten pegar un archivo «compose»:

- **Portainer:** *Stacks* > *Add stack*.
- **CasaOS:** *+* > *Instalar una app personalizada* > *Importar*.
- **TrueNAS SCALE 24.10 o posterior:** *Apps* > *Discover* > menú ⋮ > *Install via YAML*.
- **Dockge:** *+ Componer*.

En cualquiera de ellos, pega [`install/nas/docker-compose.yml`](install/nas/docker-compose.yml), cambia la IP y
despliégalo. La contraseña está en el registro (*logs*) del contenedor `octopus`.

> En Portainer y TrueNAS, las carpetas `./datos` y `./copias` deben ser rutas completas, por ejemplo
> `/mnt/datos/octopus/datos` y `/mnt/datos/octopus/copias`.

## Proxmox VE

En la web de Proxmox, abre el nodo, pulsa **Shell** y pega:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/josemurajo/OCTOPUS/main/install/proxmox/octopus-lxc.sh)"
```

- Te hace 3 preguntas: pulsa Enter en todas para aceptar lo recomendado.
- Crea un contenedor Debian sin privilegios con Docker y OCTOPUS dentro, que arranca solo con Proxmox.
- Al terminar te dice la dirección del panel y la contraseña.
- No toca ninguna otra máquina de tu Proxmox.

## Un ordenador o servidor Linux normal

Usa el instalador de siempre, que lo prepara todo solo: `sudo bash instalar_servidor.sh` (ver [README](README.md)).

---

## Preguntas frecuentes

**¿Dónde se guardan las copias?** En la carpeta `copias`, junto al archivo compose (en Unraid,
`/mnt/user/octopus-copias`). Van cifradas: aunque alguien se lleve el disco, no puede leerlas.

**¿Y si cambio la IP del NAS?** Cambia la línea `OCTOPUS_IP` y vuelve a desplegar. Los equipos siguen
funcionando.

**¿Cómo actualizo?**
- Synology y QNAP: en el proyecto, pulsa *Acción* > *Construir* (o *Actualizar*).
- Portainer: *Pull and redeploy*.
- Unraid: *Check for updates*.

Tus datos no se pierden: están en las carpetas `datos` y `copias`.

**Cambié los puertos y los equipos no conectan.** Si cambias el número de la izquierda en `ports`
(por ejemplo `9443:8080`), pon el mismo número en `OCTOPUS_PUERTO_PANEL` (o en `OCTOPUS_PUERTO_ALMACEN`, si
cambiaste el del almacén).
