# Bot de alertas de criptomonedas

Este bot vigila el mercado completo de Solana, Base, BNB Chain y Monad (las redes de FOMO) **cada 10 minutos, las 24 horas**, y te escribe por **Telegram** cuando:

- 🟢 encuentra una moneda (memecoins incluidas) que va **subiendo de forma sostenida** y tiene un buen punto de entrada;
- 🎯 una señal llega a su objetivo (vende la mitad o el resto);
- 🔴 una señal toca el stop (sal para no perder más);
- ⚠️ una moneda que estás vigilando se está debilitando.

Te llegan los avisos aunque tengas el celular bloqueado o la computadora apagada, porque el bot corre en internet (GitHub), no en tu equipo.

**El bot no compra ni vende.** Tú decides y operas en FOMO.

---

## Cómo decide

**1. Busca en todo el mercado.** Toma las monedas en tendencia de cada red (GeckoTerminal) y revisa sus números (DEX Screener).

**2. Exige subida sostenida:**
- sube en 1 hora, en 6 horas y en 24 horas, las tres a la vez;
- hay más compras que ventas;
- no subió más de 60 % en una hora (eso suele terminar en desplome);
- tiene al menos 24 horas de vida, $75 mil de liquidez, $150 mil de volumen diario y $300 mil de capitalización.

**3. Descarta las que parecen estafa** (GoPlus y RugCheck):
- monedas que no dejan vender (*honeypot*);
- impuestos de compra o venta mayores de 10 %;
- un creador que todavía puede emitir más monedas, congelar las tuyas o cambiar los saldos;
- pocas billeteras dueñas de más de la mitad de la moneda.

Si no puede revisar la seguridad de una moneda, la descarta.

**4. Mira el gráfico de 15 minutos.** Solo avisa si las medias móviles están en orden alcista (9 > 21 > 50), la fuerza (RSI) está entre 50 y 75 y hay uno de estos dos puntos de entrada:
- **retroceso**: el precio bajó a la media de 21 velas y está rebotando;
- **ruptura**: el precio rompió el máximo de las últimas 6 horas con mucho volumen.

**5. Calcula la salida antes de que entres.**
- **Stop:** queda entre 4 % y 15 % por debajo de la entrada. Si haría falta más, la moneda es demasiado loca y no avisa.
- **Objetivo 1:** 1,5 veces lo que arriesgas. Ahí vendes la mitad y subes el stop a tu precio de entrada; desde ese momento ya no puedes perder en esa operación.
- **Objetivo 2:** 3 veces lo que arriesgas. Ahí vendes el resto.

> Es un sistema de reglas, no una bola de cristal. Habrá señales que salgan mal: el stop está para que esas pérdidas sean pequeñas. Las memecoins pueden caer 50 % en minutos. Nunca pongas dinero que no puedas perder.

---

## Instalación (unos 20 minutos, una sola vez)

### Paso 1: crea tu bot de Telegram

1. En Telegram, busca **@BotFather** (tiene una palomita azul) y ábrelo.
2. Escríbele `/newbot`.
3. Te pide un nombre: por ejemplo, `Mis alertas cripto`.
4. Te pide un usuario que termine en `bot`: por ejemplo, `alertas_cripto_jose_bot`.
5. Te responde con un **token**, algo como `7123456789:AAH...`. Cópialo y guárdalo; es la clave de tu bot y **no se la compartas a nadie**.

### Paso 2: crea tu cuenta y tu repositorio en GitHub

1. Entra a **github.com** y crea una cuenta gratis (o inicia sesión).
2. Arriba a la derecha, pulsa **+** y luego **New repository**.
3. En *Repository name* escribe `cripto-bot`.
4. Elige **Public**. Así GitHub te da tiempo ilimitado gratis para que el bot corra cada 10 minutos. Tu token de Telegram queda protegido aunque el repositorio sea público.
5. Pulsa **Create repository**.

### Paso 3: sube los archivos del bot

1. Descomprime `cripto-bot.zip` en tu computadora. Verás `bot.py`, `config.json`, `README.md` y una carpeta `.github`.
2. En la página de tu repositorio nuevo, pulsa el enlace **uploading an existing file**.
3. Arrastra **todo** lo que está dentro de la carpeta descomprimida, **incluida la carpeta `.github`**, a la ventana del navegador.
4. Abajo, pulsa **Commit changes**.
5. Comprueba que en el repositorio aparezca la carpeta `.github`. Si no aparece, el bot no arrancará: vuelve a arrastrar esa carpeta sola.

### Paso 4: guarda el token de Telegram

1. En tu repositorio, entra a **Settings**, luego **Secrets and variables** y luego **Actions**.
2. Pulsa **New repository secret**.
3. En *Name* escribe exactamente `TELEGRAM_TOKEN`.
4. En *Secret* pega el token del paso 1.
5. Pulsa **Add secret**.

Después, en **Settings**, **Actions** y luego **General**, busca *Workflow permissions*, marca **Read and write permissions** y pulsa **Save**. Esto le permite al bot guardar su memoria.

### Paso 5: conecta el bot contigo y pruébalo

1. En Telegram, busca tu bot por su usuario (`alertas_cripto_jose_bot`), ábrelo y pulsa **Iniciar** (o escribe `/start`).
2. En GitHub, entra a la pestaña **Actions**. Si te pide habilitar los *workflows*, acéptalo.
3. A la izquierda, pulsa **Bot de cripto** y luego **Run workflow**. Marca la casilla *Enviar un mensaje de prueba* y pulsa el botón verde **Run workflow**.
4. En uno o dos minutos te llegará por Telegram un "✅ ¡Listo! Ya estoy conectado contigo" y un mensaje de prueba.

### Paso 6 (opcional): recibe los avisos también por WhatsApp

WhatsApp no deja que los bots escriban libremente, así que se usa **CallMeBot**, un servicio gratuito para enviarte mensajes a ti misma. Por WhatsApp solo te llegan los avisos; los comandos (`/compre`, `/estado`) siguen siendo por Telegram.

1. Entra a **callmebot.com/blog/free-api-whatsapp-messages** y copia el número de WhatsApp de CallMeBot que aparece ahí (cambia de vez en cuando; usa siempre el de esa página).
2. Guárdalo en tus contactos y mándale por WhatsApp exactamente: `I allow callmebot to send me messages`
3. En uno o dos minutos te contesta con tu **APIKEY** (un número). Si no llega, espera 24 horas y repite.
4. En GitHub (**Settings**, **Secrets and variables**, **Actions**) crea dos secretos más:
   - `WHATSAPP_PHONE`: tu número en formato internacional, por ejemplo `+18291234567`
   - `CALLMEBOT_APIKEY`: el número que te mandó CallMeBot
5. Repite la prueba del paso 5: el mensaje debe llegarte a Telegram y a WhatsApp.

Tu número queda guardado como secreto: no aparece en ninguna parte pública del repositorio. Si algún día WhatsApp te dice "Your account is paused", mándale `resume` al contacto de CallMeBot.

Desde ese momento el bot corre solo cada 10 minutos. **Solo te escribe cuando hay algo**, así que puede pasar horas callado si el mercado no da buenas entradas.

---

## Cómo se usa

Cuando te llegue una 🟢 **OPORTUNIDAD DE ENTRADA**:

1. Copia la dirección de la moneda que viene en el mensaje y búscala en FOMO.
2. Si el precio todavía está por debajo del "no compres si ya pasó de", puedes entrar.
3. Avísale al bot: `/compre SIMBOLO PRECIO`, por ejemplo `/compre GATO 0.0017`. El bot ajusta el stop y los objetivos a tu precio y te dice cuándo salir.
4. Cuando te diga **objetivo 1**, vende la mitad. Cuando te diga **objetivo 2** o **SALIR**, vende el resto.
5. Si vendiste por tu cuenta: `/vendi SIMBOLO`.

Otros comandos: `/estado` (lo que está vigilando) y `/ayuda`.

---

## Ajustes (archivo `config.json`)

Para cambiar algo, abre `config.json` en GitHub, pulsa el lápiz ✏️, cambia el número y pulsa **Commit changes**.

| Ajuste | Qué hace | Valor inicial |
| --- | --- | --- |
| `capital_usd` | El dinero que tienes para operar. Si lo pones, cada señal te sugiere cuánto comprar. | 0 (no sugiere monto) |
| `riesgo_por_operacion_pct` | El % de tu capital que aceptas perder si una operación sale mal. | 2 |
| `max_por_operacion_pct` | El % máximo de tu capital que va a una sola moneda. | 25 |
| `comision_fomo_usd` | La comisión de FOMO por cada compra o venta. | 1 |
| `liquidez_minima_usd` | Liquidez mínima. Más alta, más segura, pero menos señales. | 75000 |
| `edad_minima_horas` | Cuántas horas de vida debe tener la moneda. Bajarla da más señales y más riesgo de estafa. | 24 |
| `stop_maximo_pct` | Si el stop tendría que quedar más abajo que esto, ignora la moneda. | 15 |
| `max_alertas_por_vuelta` | Cuántas entradas te manda como máximo cada 10 minutos. | 3 |
| `redes` | Las redes que vigila. | solana, base, bsc, monad |

**Ejemplo:** con `capital_usd` en 300, riesgo de 2 % y un stop de 8 %, el bot te sugiere comprar unos $75 (el tope de 25 %). Si toca el stop, pierdes unos $8, comisiones incluidas.

---

## Bueno saber

- **Es gratis**: GitHub Actions es gratis en repositorios públicos y las fuentes de datos también.
- **Lo que se ve en público**: el archivo `state.json` es la memoria del bot (las señales que te mandó). Al ser el repositorio público, cualquiera puede verlo, pero no contiene tu nombre, tu token ni tu dinero.
- **Puede haber retrasos**: a veces GitHub tarda unos minutos más en arrancar el bot, y las fuentes gratis pueden fallar en alguna vuelta. En ese caso, el bot lo intenta de nuevo 10 minutos después.
- **Monad**: si el servicio de seguridad todavía no cubre bien esa red, esas monedas se descartan por precaución.
- **Para pausarlo**: en **Actions**, entra a **Bot de cripto**, pulsa **⋯** y luego **Disable workflow**.
- **Si GitHub te avisa que el workflow se desactivó por inactividad**, entra a **Actions** y vuelve a activarlo.

*No es asesoría financiera. Es software que lee datos públicos y aplica reglas.*
