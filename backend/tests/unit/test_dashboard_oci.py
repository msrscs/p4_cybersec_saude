"""ADR-0027: períodos da série e soma do que passa do limite de linhas."""

from datetime import date

from app.repositories.dashboard_oci import EtapasDoGrupo
from app.services.dashboard_oci import dobrar_etapas, periodos


def test_semanas_comecam_na_segunda_e_incluem_o_fim() -> None:
    saida = periodos(date(2026, 10, 1), date(2026, 10, 19), "week")
    assert saida == [date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)]


def test_meses_atravessam_a_virada_do_ano() -> None:
    saida = periodos(date(2025, 11, 20), date(2026, 2, 3), "month")
    assert saida == [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]


def test_ate_o_limite_nao_cria_outros_e_ordena_pelo_total() -> None:
    grupos = [EtapasDoGrupo(f"U{i}", realizado=i) for i in range(1, 9)]
    saida = dobrar_etapas(grupos)
    assert [g.nome for g in saida] == [f"U{i}" for i in range(8, 0, -1)]


def test_acima_do_limite_soma_o_restante_em_outros() -> None:
    grupos = [EtapasDoGrupo(f"U{i}", realizado=i, faltou=1) for i in range(1, 11)]
    saida = dobrar_etapas(grupos)
    assert len(saida) == 8 and saida[-1].nome == "Outros"
    assert saida[-1].realizado == 1 + 2 + 3 and saida[-1].faltou == 3
    assert sum(g.realizado for g in saida) == sum(g.realizado for g in grupos)
