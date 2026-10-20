# Componentes de terceros

OCTOPUS Zero-Touch (AGPL-3.0-or-later) usa estos componentes de otros proyectos, cada uno con su licencia.
Todas permiten usarlos junto a la AGPL-3.0. Los textos completos de cada licencia vienen con cada componente
(carpeta del paquete instalado, o la web del proyecto). Esta lista la genera `python herramientas/terceros.py`.

## Programas que se descargan al instalar

| Componente | Licencia | Web | Para qué |
|---|---|---|---|
| restic | BSD-2-Clause | https://github.com/restic/restic | Las copias (en el servidor y en cada equipo) |
| rest-server | BSD-2-Clause | https://github.com/restic/rest-server | El almacén de copias del servidor |
| Python | PSF-2.0 | https://www.python.org | Ejecuta el servidor y el agente |
| Docker CLI | Apache-2.0 | https://github.com/docker/cli | Sala de análisis (solo en el servidor Docker) |
| ansible-core | GPL-3.0-or-later | https://github.com/ansible/ansible | Solo si se usa «octopus.sh desplegar» (agentes en muchos Linux a la vez): se instala entonces, aparte del código de OCTOPUS |
| smartmontools | GPL-2.0-or-later | https://www.smartmontools.org | Salud del disco en la monitorización; se instala con el gestor de paquetes del sistema |
| YARA | BSD-3-Clause | https://github.com/VirusTotal/yara | Análisis de archivos sospechosos (servidor Docker) |
| OpenSSL | Apache-2.0 | https://www.openssl.org | Certificados del servidor |

## Bibliotecas de Python (`requirements.txt` y lo que necesitan)

| Componente | Versión revisada | Licencia | Web |
|---|---|---|---|
| bcrypt | 5.0.0 | Apache-2.0 | https://github.com/pyca/bcrypt/ |
| blinker | 1.9.0 | MIT | https://github.com/pallets-eco/blinker/ |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi |
| cffi | 2.1.1 | MIT-0 | https://github.com/python-cffi/cffi |
| charset-normalizer | 3.5.1 | MIT | https://charset-normalizer.readthedocs.io/ |
| click | 8.5.0 | BSD-3-Clause | https://github.com/pallets/click/ |
| cryptography | 50.0.1 | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography/ |
| Deprecated | 3.0.0 | MIT | https://github.com/laurent-laporte-pro/deprecated |
| Flask | 3.1.3 | BSD-3-Clause | https://github.com/pallets/flask/ |
| Flask-Limiter | 4.1.1 | MIT | https://github.com/alisaifee/flask-limiter |
| flask-talisman | 1.1.0 | Apache-2.0 | https://github.com/wntrblm/flask-talisman |
| gunicorn | 26.2.0 | MIT | https://github.com/benoitc/gunicorn |
| idna | 3.19 | BSD-3-Clause | https://github.com/kjd/idna |
| invoke | 3.0.3 | BSD-2-Clause | https://github.com/pyinvoke/invoke |
| itsdangerous | 2.2.0 | BSD | https://github.com/pallets/itsdangerous/ |
| Jinja2 | 3.1.6 | BSD | https://github.com/pallets/jinja/ |
| ldap3 | 2.9.1 | LGPL-3.0 | https://github.com/cannatag/ldap3 |
| limits | 5.8.0 | MIT | https://github.com/alisaifee/limits |
| markdown-it-py | 4.2.0 | MIT | https://github.com/executablebooks/markdown-it-py |
| MarkupSafe | 3.0.3 | BSD-3-Clause | https://github.com/pallets/markupsafe/ |
| mdit-py-plugins | 0.6.1 | MIT | https://github.com/executablebooks/mdit-py-plugins |
| mdurl | 0.1.2 | MIT | https://github.com/executablebooks/mdurl |
| ordered-set | 4.1.0 | MIT | https://github.com/rspeer/ordered-set |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| paramiko | 5.0.0 | LGPL-2.1 | https://github.com/paramiko/paramiko |
| platformdirs | 4.13.0 | MIT | https://github.com/tox-dev/platformdirs |
| pyasn1 | 0.6.4 | BSD-2-Clause | https://github.com/pyasn1/pyasn1 |
| pycparser | 3.0 | BSD-3-Clause | https://github.com/eliben/pycparser |
| Pygments | 2.21.0 | BSD-2-Clause | https://github.com/pygments/pygments |
| PyJWT | 2.15.1 | MIT | https://github.com/jpadilla/pyjwt |
| PyNaCl | 1.6.2 | Apache-2.0 | https://github.com/pyca/pynacl/ |
| PyYAML | 6.0.3 | MIT | https://pyyaml.org/ |
| qrcode | 8.2 | BSD | https://github.com/lincolnloop/python-qrcode |
| requests | 2.34.2 | Apache-2.0 | https://github.com/psf/requests |
| rich | 15.0.0 | MIT | https://github.com/Textualize/rich |
| textual | 8.2.8 | MIT | https://github.com/Textualize/textual |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| urllib3 | 2.7.0 | MIT | https://urllib3.readthedocs.io |
| Werkzeug | 3.1.8 | BSD-3-Clause | https://github.com/pallets/werkzeug/ |
| wrapt | 2.5.1 | BSD-2-Clause | https://github.com/GrahamDumpleton/wrapt |
| cheroot | (solo Windows) | BSD-3-Clause | https://github.com/cherrypy/cheroot |
