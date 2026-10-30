"""Mensagens de erro do servidor em inglês e espanhol.

O app (e a página de agendamento) mandam o cabeçalho `Accept-Language`. O servidor continua escrevendo as mensagens em português
(a chave) e, na hora de responder um erro, troca pelo texto do idioma pedido se houver tradução. Sem tradução, ou com qualquer
outro idioma, sai o português: nunca falha. O teste test_i18n_servidor.py confere que TODA mensagem fixa do servidor tem tradução.
"""
from __future__ import annotations

from typing import Optional

TRADUCOES: dict[str, tuple[str, str]] = {
    "A assinatura de planos pagos ainda não está disponível.": ("Paid plan subscriptions aren't available yet.", "Las suscripciones a planes de pago aún no están disponibles."),
    "A conta Microsoft não informou um e-mail": ("The Microsoft account didn't provide an email", "La cuenta de Microsoft no informó un correo"),
    "Acesso negado": ("Access denied", "Acceso denegado"),
    "Agendamento não encontrado": ("Booking not found", "Reserva no encontrada"),
    "Aguarde um minuto antes de pedir outro código.": ("Wait a minute before requesting another code.", "Espera un minuto antes de pedir otro código."),
    "Assinatura de outro usuário": ("Subscription belongs to another user", "Suscripción de otro usuario"),
    "Assinatura de plano requer gateway Stripe real": ("Plan subscriptions require the real Stripe gateway", "La suscripción a planes requiere el gateway real de Stripe"),
    "Cartão não cadastrado": ("No card on file", "Tarjeta no registrada"),
    "Cartão recusado na captura. Contate o cliente.": ("Card declined on capture. Contact the client.", "Tarjeta rechazada al cobrar. Contacta al cliente."),
    "Cartão recusado pela operadora. Tente outro cartão.": ("Card declined by the issuer. Try another card.", "Tarjeta rechazada por el emisor. Prueba con otra tarjeta."),
    "Conclua o cadastro no Stripe antes de abrir o painel.": ("Finish your Stripe registration before opening the dashboard.", "Completa tu registro en Stripe antes de abrir el panel."),
    "Conecte sua conta do Stripe primeiro.": ("Connect your Stripe account first.", "Conecta primero tu cuenta de Stripe."),
    "Confirmação já em processamento por outra requisição": ("Confirmation is already being processed by another request", "La confirmación ya está siendo procesada por otra solicitud"),
    "Connect não habilitado na conta Stripe da plataforma. Ative em https://dashboard.stripe.com/connect": ("Connect isn't enabled on the platform's Stripe account. Enable it at https://dashboard.stripe.com/connect", "Connect no está habilitado en la cuenta de Stripe de la plataforma. Actívalo en https://dashboard.stripe.com/connect"),
    "Connect requer gateway Stripe real": ("Connect requires the real Stripe gateway", "Connect requiere el gateway real de Stripe"),
    "Código inválido ou expirado.": ("Invalid or expired code.", "Código inválido o vencido."),
    "E-mail do Google não verificado": ("Google email not verified", "Correo de Google no verificado"),
    "E-mail ou senha incorretos.": ("Incorrect email or password.", "Correo o contraseña incorrectos."),
    "Esse horário acabou de ser reservado por outro cliente. Escolha outro.": ("That time was just booked by another client. Pick another.", "Ese horario acaba de ser reservado por otro cliente. Elige otro."),
    "Este profissional ainda não habilitou os recebimentos pelo ShowUp. Tente de novo mais tarde.": ("This professional hasn't enabled payouts on ShowUp yet. Please try again later.", "Este profesional aún no habilitó los cobros en ShowUp. Inténtalo de nuevo más tarde."),
    "Falha ao autorizar cartão": ("Failed to authorize the card", "Error al autorizar la tarjeta"),
    "Falha ao cancelar hold junto ao gateway": ("Failed to cancel the hold with the payment gateway", "Error al cancelar la reserva en la tarjeta con el gateway"),
    "Falha ao confirmar cartão junto ao gateway": ("Failed to confirm the card with the payment gateway", "Error al confirmar la tarjeta con el gateway"),
    "Falha ao criar assinatura junto ao gateway": ("Failed to create the subscription with the payment gateway", "Error al crear la suscripción con el gateway"),
    "Este profissional recebe pelo Mercado Pago. Agende pelo link de agendamento dele, com cartão ou Pix.": ("This professional is paid through Mercado Pago. Book through their booking link, with card or Pix.", "Este profesional recibe por Mercado Pago. Reserva por su enlace de reservas, con tarjeta o Pix."),
    "Este profissional não recebe pelo Mercado Pago. Recarregue a página e tente de novo.": ("This professional isn't paid through Mercado Pago. Reload the page and try again.", "Este profesional no recibe por Mercado Pago. Recarga la página e inténtalo de nuevo."),
    "Informe seu e-mail para pagar com Pix.": ("Enter your email to pay with Pix.", "Ingresa tu correo para pagar con Pix."),
    "O Mercado Pago ainda não está disponível no ShowUp.": ("Mercado Pago isn't available on ShowUp yet.", "Mercado Pago aún no está disponible en ShowUp."),
    "Conecte sua conta do Mercado Pago primeiro.": ("Connect your Mercado Pago account first.", "Conecta primero tu cuenta de Mercado Pago."),
    "O Mercado Pago só recebe em reais. Mude a moeda e os serviços para real (BRL) antes.": ("Mercado Pago only receives in Brazilian reais. Change your currency and services to real (BRL) first.", "Mercado Pago solo recibe en reales. Cambia primero la moneda y los servicios a real (BRL)."),
    "O Mercado Pago só recebe em reais. Para usar outra moeda, passe a receber pelo Stripe.": ("Mercado Pago only receives in Brazilian reais. To use another currency, switch to receiving through Stripe.", "Mercado Pago solo recibe en reales. Para usar otra moneda, pasa a recibir por Stripe."),
    "Você ainda tem reservas abertas no Mercado Pago. Confirme ou cancele antes de desconectar.": ("You still have open holds on Mercado Pago. Confirm or cancel them before disconnecting.", "Todavía tienes reservas abiertas en Mercado Pago. Confírmalas o cancélalas antes de desconectar."),
    "Para reservar com cartão use Visa, Mastercard, American Express ou Cabal. Ou pague com Pix.": ("To book with a card, use Visa, Mastercard, American Express or Cabal. Or pay with Pix.", "Para reservar con tarjeta usa Visa, Mastercard, American Express o Cabal. O paga con Pix."),
    "Esse horário está distante demais: a reserva no cartão vale por 5 dias. Escolha um horário mais próximo.": ("That time is too far ahead: the card hold lasts 5 days. Choose a closer time.", "Ese horario está demasiado lejos: la reserva en la tarjeta dura 5 días. Elige un horario más cercano."),
    "O preço deste plano está sendo atualizado. Tente de novo mais tarde.": ("This plan's price is being updated. Please try again later.", "El precio de este plan se está actualizando. Inténtalo de nuevo más tarde."),
    "Falha ao gerar cobrança Pix junto ao gateway": ("Failed to create the Pix charge with the payment gateway", "Error al generar el cobro Pix con el gateway"),
    "Falha ao gerar link de onboarding junto ao gateway": ("Failed to generate the onboarding link with the payment gateway", "Error al generar el enlace de registro con el gateway"),
    "Falha ao processar pagamento junto ao gateway": ("Failed to process the payment with the payment gateway", "Error al procesar el pago con el gateway"),
    "Gateway de pagamento indisponível no momento. Tente novamente em instantes.": ("The payment gateway is unavailable right now. Please try again in a moment.", "El gateway de pago no está disponible por el momento. Inténtalo de nuevo en unos instantes."),
    "Gateway de pagamento indisponível. Tente confirmar novamente.": ("The payment gateway is unavailable. Please try confirming again.", "El gateway de pago no está disponible. Intenta confirmar de nuevo."),
    "Hold já processado ou confirmação em andamento — não é mais possível cancelar": ("Hold already processed or confirmation in progress — it can no longer be canceled", "La reserva ya fue procesada o la confirmación está en curso: ya no es posible cancelar"),
    "Horário deve ser futuro": ("The time must be in the future", "El horario debe ser futuro"),
    "Informe seu nome (de 2 a 80 caracteres).": ("Enter your name (2 to 80 characters).", "Ingresa tu nombre (de 2 a 80 caracteres)."),
    "Informe um e-mail válido.": ("Enter a valid email.", "Ingresa un correo válido."),
    "Invalid session": ("Invalid session", "Sesión inválida"),
    "Janela expirada": ("Window expired", "Plazo vencido"),
    "Missing bearer token": ("Missing bearer token", "Falta el token de acceso"),
    'Muitas tentativas. Tente de novo em alguns minutos ou use "Esqueci minha senha".': ('Too many attempts. Try again in a few minutes or use "Forgot my password".', 'Demasiados intentos. Inténtalo de nuevo en unos minutos o usa "Olvidé mi contraseña".'),
    "Nenhuma assinatura pendente pra confirmar": ("No pending subscription to confirm", "Ninguna suscripción pendiente por confirmar"),
    "Não consegui falar com o serviço de notificações agora. Tente de novo em instantes.": ("Couldn't reach the notification service right now. Please try again in a moment.", "No pude comunicarme con el servicio de notificaciones ahora. Inténtalo de nuevo en unos instantes."),
    "Não conseguimos enviar o e-mail agora. Tente de novo em instantes.": ("We couldn't send the email right now. Please try again in a moment.", "No pudimos enviar el correo ahora. Inténtalo de nuevo en unos instantes."),
    "Não encontrado": ("Not found", "No encontrado"),
    "Não foi possível abrir o painel do Stripe agora. Tente de novo.": ("Couldn't open the Stripe dashboard right now. Please try again.", "No fue posible abrir el panel de Stripe ahora. Inténtalo de nuevo."),
    "Não foi possível preparar o pagamento com cartão agora. Tente de novo.": ("Couldn't prepare the card payment right now. Please try again.", "No fue posible preparar el pago con tarjeta ahora. Inténtalo de nuevo."),
    "Não foi possível preparar o teste grátis agora. Tente de novo.": ("Couldn't set up the free trial right now. Please try again.", "No fue posible preparar la prueba gratis ahora. Inténtalo de nuevo."),
    "Não foi possível verificar o login com o Google agora. Tente de novo.": ("Couldn't verify the Google sign-in right now. Please try again.", "No fue posible verificar el inicio de sesión con Google ahora. Inténtalo de nuevo."),
    "O cadastro por e-mail ainda não está disponível. Use o login com Google ou Microsoft.": ("Email sign-up isn't available yet. Use Google or Microsoft sign-in.", "El registro por correo aún no está disponible. Usa el inicio de sesión con Google o Microsoft."),
    "O seu cartão só permite reservar por poucos dias. Escolha um horário mais próximo.": ("Your card only allows holds for a few days. Choose a closer time.", "Tu tarjeta solo permite reservar por pocos días. Elige un horario más cercano."),
    "Papel não definido": ("Role not set", "Rol no definido"),
    "Pix indisponível no momento. Pague com cartão.": ("Pix is unavailable right now. Pay by card.", "Pix no está disponible por el momento. Paga con tarjeta."),
    "Pix requer gateway Stripe real": ("Pix requires the real Stripe gateway", "Pix requiere el gateway real de Stripe"),
    "Plano diferente do que foi preparado": ("Plan differs from the one prepared", "Plan diferente al que se preparó"),
    "Resposta da Microsoft sem identificador": ("Microsoft response without an identifier", "Respuesta de Microsoft sin identificador"),
    "Serviço não encontrado": ("Service not found", "Servicio no encontrado"),
    "Teste grátis indisponível: ele só vale uma vez, pra quem ainda não assinou nenhum plano": ("Free trial unavailable: it only applies once, to those who haven't subscribed to any plan", "Prueba gratis no disponible: solo vale una vez, para quien aún no se suscribió a ningún plan"),
    "Token do Google sem e-mail": ("Google token without an email", "Token de Google sin correo"),
    "User not found": ("User not found", "Usuario no encontrado"),
    "servico_id não pertence ao profissional_id informado": ("servico_id does not belong to the given profissional_id", "servico_id no pertenece al profissional_id indicado"),
    "taxa_no_show > valor": ("no-show fee > price", "tarifa por ausencia > valor"),
    "Este aparelho ainda não está registrado para receber notificações. Abra o app no celular (não no emulador), permita as notificações e tente de novo.": ("This device isn't registered to receive notifications yet. Open the app on your phone (not an emulator), allow notifications and try again.", "Este dispositivo aún no está registrado para recibir notificaciones. Abre la app en el celular (no en el emulador), permite las notificaciones e inténtalo de nuevo."),
    "Não conseguimos cancelar a cobrança do seu plano agora. Tente de novo em instantes — sua conta não foi excluída.": ("We couldn't cancel your plan's billing right now. Please try again in a moment — your account was not deleted.", "No pudimos cancelar el cobro de tu plan ahora. Inténtalo de nuevo en unos instantes: tu cuenta no fue eliminada."),
    "Você tem agendamentos pendentes ou futuros. Cancele ou aguarde eles terminarem antes de excluir sua conta.": ("You have pending or upcoming bookings. Cancel them or wait for them to finish before deleting your account.", "Tienes reservas pendientes o futuras. Cancélalas o espera a que terminen antes de eliminar tu cuenta."),
    # agenda.MENSAGENS (mensagens montadas por motivo, não literais no HTTPException)
    "Este profissional ainda não abriu horários para agendamento.": ("This professional hasn't opened any times for booking yet.", "Este profesional aún no abrió horarios para reservar."),
    "Esse horário ainda não está aberto para agendamento. Escolha um dos horários disponíveis.": ("That time isn't open for booking yet. Choose one of the available times.", "Ese horario aún no está abierto para reservar. Elige uno de los horarios disponibles."),
    "Esse horário está distante demais: a reserva no cartão vale por 7 dias. Escolha um horário mais próximo.": ("That time is too far away: a card hold lasts 7 days. Choose a closer time.", "Ese horario está demasiado lejos: la reserva en la tarjeta dura 7 días. Elige un horario más cercano."),
    "Esse horário não está disponível. Escolha um dos horários mostrados.": ("That time isn't available. Choose one of the times shown.", "Ese horario no está disponible. Elige uno de los horarios mostrados."),
}


def idioma_da_requisicao(accept_language: Optional[str]) -> str:
    """"en-US,en;q=0.9" -> "en"; "es-MX" -> "es"; qualquer outra coisa (inclusive pt, vazio ou lixo) -> "pt"."""
    if not accept_language:
        return "pt"
    primeiro = accept_language.split(",")[0].split(";")[0].strip().lower().replace("_", "-")
    base = primeiro.split("-")[0]
    return base if base in ("en", "es") else "pt"


def traduzir(mensagem, idioma: str):
    """Mensagem em português -> idioma pedido. Sem tradução (ou não texto), devolve a mensagem como veio."""
    if not isinstance(mensagem, str) or idioma == "pt":
        return mensagem
    par = TRADUCOES.get(mensagem)
    if par is None:
        return mensagem
    return par[0] if idioma == "en" else par[1]
