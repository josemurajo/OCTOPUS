# Evaluación de impacto de la monitorización — plantilla medio rellena

> Sirve para decidir si la monitorización es necesaria y proporcionada (art. 35 RGPD). La AEPD incluye en su lista de
> tratamientos que pueden necesitarla los que observan de forma sistemática a trabajadores. Con la configuración por
> defecto de OCTOPUS (sin usuario de sesión, solo datos técnicos) el riesgo es bajo, pero **decídelo tú con tu
> asesor**. Rellena los [corchetes].

## 1. Descripción
- **Qué:** datos técnicos de los equipos (uso, temperatura, discos, red, batería, inventario) y, si se activa, los
  programas abiertos y el usuario con sesión.
- **De quién:** trabajadores que usan los [N] equipos monitorizados.
- **Para qué:** detectar averías y problemas de seguridad a tiempo. No para medir ni controlar el trabajo.
- **Dónde:** solo en el servidor de la empresa; nadie de fuera tiene acceso.

## 2. Necesidad y proporcionalidad
| Pregunta | Respuesta |
|---|---|
| ¿Se puede conseguir lo mismo con menos datos? | Se ha desactivado [el usuario con sesión / los programas abiertos] porque no son necesarios para [motivo]. |
| ¿Se monitoriza solo lo necesario? | Solo en los equipos [lista o criterio], activados uno a uno. |
| ¿Cuánto se guarda? | [N] días (Ajustes → Funciones → Monitorización). |
| ¿Se ha informado? | Sí, con la nota informativa entregada el [fecha] y a los representantes el [fecha]. |
| ¿Quién accede? | [Personas], con doble autenticación; todo queda en el registro de actividad. |

## 3. Riesgos y medidas
| Riesgo | Probabilidad / gravedad | Medida |
|---|---|---|
| Uso para controlar la actividad del trabajador | [baja] / [alta] | Prohibido por política interna; solo datos técnicos; registro de quién mira cada equipo |
| Acceso indebido al panel | [baja] / [media] | Doble autenticación, bloqueo de intentos, panel solo desde la red de la oficina (opcional) |
| Se guarda más de lo necesario | [baja] / [baja] | Historial limitado a [N] días; programas y usuario desactivables |

## 4. Conclusión
[El tratamiento es necesario y proporcionado con las medidas indicadas / hay que cambiar...].
Fecha: [ ] · Responsable: [ ] · Revisado por: [asesor / DPD]
