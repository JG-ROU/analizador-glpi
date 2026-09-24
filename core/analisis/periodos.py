"""Períodos de cálculo: semana ISO, mes o rango (RN-01).

Un período es el intervalo [inicio, fin): incluye el inicio y excluye el fin.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

SEMANA = "SEMANA"
MES = "MES"
RANGO = "RANGO"

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "octubre", "noviembre", "diciembre",
)


@dataclass(frozen=True)
class Periodo:
    inicio: datetime
    fin: datetime
    granularidad: str

    @property
    def etiqueta(self) -> str:
        ultimo_dia = (self.fin - timedelta(days=1)).date()
        if self.granularidad == SEMANA:
            anio, semana, _ = self.inicio.isocalendar()
            return (
                f"Semana {semana} de {anio} "
                f"({self.inicio:%d/%m} – {ultimo_dia:%d/%m})"
            )
        if self.granularidad == MES:
            return f"{MESES[self.inicio.month - 1].capitalize()} {self.inicio.year}"
        return f"{self.inicio:%d/%m/%Y} – {ultimo_dia:%d/%m/%Y}"

    @property
    def codigo(self) -> str:
        """AAAA-Www o AAAA-MM, como en la tabla snapshot; el rango usa sus fechas."""
        if self.granularidad == SEMANA:
            anio, semana, _ = self.inicio.isocalendar()
            return f"{anio}-W{semana:02d}"
        if self.granularidad == MES:
            return f"{self.inicio:%Y-%m}"
        return f"{self.inicio:%Y-%m-%d}_{(self.fin - timedelta(days=1)):%Y-%m-%d}"

    def contiene(self, fecha: datetime) -> bool:
        return self.inicio <= fecha < self.fin

    def anterior(self) -> "Periodo":
        """El período inmediatamente anterior, de la misma clase y duración."""
        if self.granularidad == SEMANA:
            return semana_de(self.inicio - timedelta(days=7))
        if self.granularidad == MES:
            return mes_de(self.inicio - timedelta(days=1))
        duracion = self.fin - self.inicio
        return Periodo(self.inicio - duracion, self.inicio, RANGO)

    def corte(self, ahora: datetime) -> datetime:
        """Fecha de corte: el fin del período, o ahora si el período no ha terminado."""
        return min(self.fin, ahora)


def _medianoche(dia: date) -> datetime:
    return datetime.combine(dia, time(0, 0))


def semana(anio: int, numero: int) -> Periodo:
    """Semana ISO: de lunes a domingo."""
    lunes = date.fromisocalendar(anio, numero, 1)
    return Periodo(_medianoche(lunes), _medianoche(lunes + timedelta(days=7)), SEMANA)


def semana_de(fecha: datetime | date) -> Periodo:
    anio, numero, _ = fecha.isocalendar()
    return semana(anio, numero)


def mes(anio: int, numero: int) -> Periodo:
    inicio = datetime(anio, numero, 1)
    siguiente = datetime(anio + 1, 1, 1) if numero == 12 else datetime(anio, numero + 1, 1)
    return Periodo(inicio, siguiente, MES)


def mes_de(fecha: datetime | date) -> Periodo:
    return mes(fecha.year, fecha.month)


def rango(desde: date, hasta: date) -> Periodo:
    """Del día `desde` al día `hasta`, ambos incluidos."""
    if hasta < desde:
        raise ValueError("La fecha final del rango es anterior a la inicial")
    return Periodo(_medianoche(desde), _medianoche(hasta + timedelta(days=1)), RANGO)


def semanas_en(periodo: Periodo) -> list[Periodo]:
    """Semanas ISO que tocan el período, para los gráficos semanales."""
    semanas = []
    actual = semana_de(periodo.inicio)
    while actual.inicio < periodo.fin:
        semanas.append(actual)
        actual = semana_de(actual.fin)
    return semanas


def ultimos(periodo: Periodo, cantidad: int) -> list[Periodo]:
    """Los `cantidad` períodos que terminan en `periodo`, del más antiguo al más reciente."""
    lista = [periodo]
    while len(lista) < cantidad:
        lista.append(lista[-1].anterior())
    return list(reversed(lista))
