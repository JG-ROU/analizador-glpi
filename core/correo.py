"""Borradores de correo .eml (spec 09).

El archivo se abre en el cliente de correo predeterminado (Outlook) para revisar
y enviar. La cabecera «X-Unsent: 1» hace que Outlook lo abra como borrador
editable. No se guardan contraseñas ni se envía nada automáticamente.
"""

import mimetypes
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

from core.errores import ErrorAplicacion


def crear_borrador(ruta: Path, asunto: str, cuerpo: str, destinatarios: str = "",
                   adjuntos: list[Path] | None = None) -> Path:
    """Escribe un .eml con el asunto, el cuerpo en texto plano y los adjuntos."""
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["To"] = destinatarios.strip()
    mensaje["Date"] = formatdate(localtime=True)
    mensaje["X-Unsent"] = "1"
    mensaje.set_content(cuerpo)
    for adjunto in adjuntos or []:
        tipo, _ = mimetypes.guess_type(adjunto.name)
        principal, secundario = (tipo or "application/octet-stream").split("/", 1)
        mensaje.add_attachment(adjunto.read_bytes(), maintype=principal, subtype=secundario, filename=adjunto.name)
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(bytes(mensaje))
    except OSError as error:
        raise ErrorAplicacion(f"No se pudo guardar el borrador de correo «{ruta.name}».", detalle=repr(error)) from error
    return ruta
