#!/usr/bin/env python3
"""Quanto sobra (ou falta) para o ShowUp em cada plano, depois de pagar o Stripe.

Uso (da raiz do projeto):
  py lancamento\\calcular-precos.py              # planos em vigor (e a proposta, se for diferente), em vários perfis
  py lancamento\\calcular-precos.py --proposta   # só a proposta
  py lancamento\\calcular-precos.py --antigos    # inclui os planos de antes de 29/10/2026

Revise uma vez por mês: confira os custos abaixo em stripe.com/br/pricing e stripe.com/br/connect/pricing
(última conferência: 29/10/2026) e rode de novo. Guia: lancamento/PRECOS-DOS-PLANOS.md.

Dinheiro em centavos inteiros e percentuais em pontos-base (100 = 1%), como no servidor.
Conta simples, sem imposto (o imposto sobre a receita do ShowUp vem depois e reduz a sobra).
"""
import argparse
import sys

# ---- Custos do Stripe Brasil (conferidos em 29/10/2026) -------------------------------------------
CARTAO_BPS, CARTAO_FIXO = 399, 39   # 3,99% + R$ 0,39 por cobrança com cartão nacional
INTERNACIONAL_BPS = 200             # + 2% para cartão internacional
CONVERSAO_BPS = 200                 # conversão de moeda: "a partir de 2%" (cobrança em moeda que não é real)
CONTA_ATIVA = 600                   # Connect: R$ 6 por conta conectada que recebeu repasse no mês
REPASSE_BPS, REPASSE_FIXO = 25, 67  # Connect: 0,25% + R$ 0,67 por repasse enviado
BILLING_BPS = 70                    # Billing: 0,7% do valor das assinaturas
REPASSES_POR_MES = 4                # calendário semanal (com repasse diário seriam ~20 x R$ 0,67)

# ---- Planos: (mensalidade em centavos, taxa por agendamento, adicional em cobrança em outra moeda) ------
# ATUAIS = o que está em vigor no servidor (PLANOS e ADICIONAL_CONVERSAO_BPS em backend/server.py; test_calcular_precos.py confere).
# PROPOSTA = onde você testa valores novos antes de mudar o servidor.
ANTIGOS_ATE_29_10_2026 = {
    "Free": (0, 1000, 0),
    "Profissional": (1990, 500, 0),
    "Ultra": (5990, 200, 0),
}
ATUAIS = {
    "Free": (0, 1000, 400),
    "Profissional": (2990, 700, 400),
    "Ultra": (6990, 550, 400),
}
PROPOSTA = dict(ATUAIS)

# ---- Perfis de profissional: (nome, agendamentos cobrados no mês, valor médio em centavos) ---------
PERFIS = [
    ("Começando: 10 x R$ 80", 10, 8000),
    ("Médio: 30 x R$ 100", 30, 10000),
    ("Cheio: 60 x R$ 120", 60, 12000),
    ("Alto valor: 20 x R$ 400", 20, 40000),
]


def pct(valor: int, bps: int) -> int:
    return valor * bps // 10_000


def custo_cobranca(valor: int, internacional: bool = False, outra_moeda: bool = False) -> int:
    bps = CARTAO_BPS + (INTERNACIONAL_BPS if internacional else 0) + (CONVERSAO_BPS if outra_moeda else 0)
    return pct(valor, bps) + CARTAO_FIXO


def sobra_mensal(plano: tuple[int, int, int], n: int, valor: int, internacional=False, outra_moeda=False) -> int:
    """Receita do ShowUp no mês com um profissional, menos tudo que o Stripe cobra da plataforma."""
    mensalidade, taxa_bps, adicional_bps = plano
    if internacional or outra_moeda:
        taxa_bps += adicional_bps
    receita = n * pct(valor, taxa_bps) + mensalidade
    custo = n * custo_cobranca(valor, internacional, outra_moeda)
    if n:
        repassado = n * (valor - pct(valor, taxa_bps))
        custo += CONTA_ATIVA + pct(repassado, REPASSE_BPS) + REPASSES_POR_MES * REPASSE_FIXO
    if mensalidade:
        custo += custo_cobranca(mensalidade) + pct(mensalidade, BILLING_BPS)
    return receita - custo


def reais(c: int) -> str:
    sinal = "-" if c < 0 else " "
    c = abs(c)
    return f"{sinal}R$ {c // 100:>5},{c % 100:02d}"


def tabela(nome: str, planos: dict) -> list[str]:
    linhas = [f"\n== {nome} ==", f"{'Perfil':<26}{'Cartão':<16}" + "".join(f"{p:>16}" for p in planos)]
    for perfil, n, valor in PERFIS:
        for rotulo, kw in (("nacional", {}), ("internac.+moeda", {"internacional": True, "outra_moeda": True})):
            linhas.append(f"{perfil:<26}{rotulo:<16}" + "".join(f"{reais(sobra_mensal(p, n, valor, **kw)):>16}" for p in planos.values()))
    return linhas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proposta", action="store_true", help="mostra só a proposta")
    ap.add_argument("--antigos", action="store_true", help="mostra também os planos de antes de 29/10/2026")
    args = ap.parse_args(argv)
    print("Sobra mensal do ShowUp por profissional (negativo = prejuízo), sem imposto.")
    if args.antigos:
        print("\n".join(tabela("Planos ANTIGOS (até 29/10/2026)", ANTIGOS_ATE_29_10_2026)))
    if not args.proposta:
        print("\n".join(tabela("Planos ATUAIS (em vigor no servidor)", ATUAIS)))
    if args.proposta or PROPOSTA != ATUAIS:
        print("\n".join(tabela("PROPOSTA", PROPOSTA)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
