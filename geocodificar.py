"""
Versão simplificada: encontra o setor censitário de cada endereço da base de busca
usando o CNEFE da Bahia.

Passos:
  1. Ler o CNEFE e guardar só os municípios que aparecem na busca.
  2. Padronizar os textos (maiúsculas, sem acento, abreviações).
  3. Para cada endereço, achar a rua mais parecida no mesmo município.
  4. Usar o número da casa para escolher o setor.

Uso:  python geocodificar.py  CAMINHO_DO_29_BA.csv  CAMINHO_DA_BASE_BUSCA.csv
"""
import re
import sys

import pandas as pd
from rapidfuzz import fuzz, process
from unidecode import unidecode

NOTA_MINIMA = 85  # similaridade mínima (0 a 100) para aceitar uma rua

ABREVIACOES = {
    "R": "RUA", "AV": "AVENIDA", "TV": "TRAVESSA", "TRAV": "TRAVESSA",
    "FAZ": "FAZENDA", "PCA": "PRACA", "ROD": "RODOVIA", "EST": "ESTRADA",
    "DR": "DOUTOR", "ENG": "ENGENHEIRO", "PE": "PADRE", "STA": "SANTA", "STO": "SANTO",
}
IGNORAR = {"DE", "DA", "DO", "DAS", "DOS", "NONE"}
TIPOS = {"RUA", "AVENIDA", "TRAVESSA", "FAZENDA", "SITIO", "DISTRITO", "PRACA",
         "RODOVIA", "ESTRADA", "CONJUNTO", "CONDOMINIO", "LOTEAMENTO", "POVOADO",
         "COMUNIDADE", "VIA", "EIXO", "PONTA", "ALAMEDA", "VILA", "CAMINHO"}

def padronizar(texto):
    """'Av. Sete de Setembro' -> 'AVENIDA SETE SETEMBRO'"""
    if pd.isna(texto):
        return ""
    texto = unidecode(str(texto)).upper()        # tira acentos, maiúsculas
    texto = re.sub(r"[^A-Z0-9 ]", " ", texto)     # tira pontuação
    palavras = [ABREVIACOES.get(p, p) for p in texto.split()]
    palavras = [p for p in palavras if p not in IGNORAR]
    return " ".join(palavras)

def tirar_tipo(nome):
    """'RUA SERGIO BONFIM' -> 'SERGIO BONFIM' (só se sobrar alguma palavra)"""
    palavras = nome.split()
    while len(palavras) > 1 and palavras[0] in TIPOS:
        palavras = palavras[1:]
    return " ".join(palavras)

def ler_numero(texto):
    """'332' -> 332 ; 'S/N', 'SN', vazio -> None"""
    achado = re.search(r"\d+", str(texto))
    if achado and int(achado.group()) > 0:
        return int(achado.group())
    return None

def carregar_cnefe(caminho, municipios):
    """Lê o CNEFE em pedaços (é grande demais para ler de uma vez)."""
    colunas = ["COD_MUNICIPIO", "COD_SETOR", "CEP", "NOM_TIPO_SEGLOGR",
               "NOM_TITULO_SEGLOGR", "NOM_SEGLOGR", "NUM_ENDERECO"]
    pedacos = []
    for pedaco in pd.read_csv(caminho, sep=";", usecols=colunas, dtype=str,
                              chunksize=500_000):
        pedaco["municipio"] = pedaco["COD_MUNICIPIO"].str[:6]  # tira o dígito verificador
        pedacos.append(pedaco[pedaco["municipio"].isin(municipios)])
    cnefe = pd.concat(pedacos)
    cnefe["rua"] = (cnefe["NOM_TITULO_SEGLOGR"].fillna("") + " " +
                    cnefe["NOM_SEGLOGR"].fillna(""))
    cnefe["tipo"] = cnefe["NOM_TIPO_SEGLOGR"].fillna("")
    cnefe["numero"] = pd.to_numeric(cnefe["NUM_ENDERECO"], errors="coerce").replace(0, None)
    return cnefe

def preferir(enderecos, condicao):
    filtrados = enderecos[condicao]
    return filtrados if len(filtrados) > 0 else enderecos

def escolher_setor(enderecos_da_rua, numero):
    setores = enderecos_da_rua["COD_SETOR"]

    if setores.nunique() == 1:                     
        return setores.iloc[0], "RUA_EM_UM_SETOR"

    if numero is not None:
        mesmo_numero = enderecos_da_rua[enderecos_da_rua["numero"] == numero]
        if len(mesmo_numero) > 0:                    # existe exatamente esse número
            return mesmo_numero["COD_SETOR"].mode()[0], "NUMERO_EXATO"

        com_numero = enderecos_da_rua.dropna(subset=["numero"])
        if len(com_numero) > 0:                      # pega o número mais próximo
            distancia = (com_numero["numero"] - numero).abs()
            return com_numero.loc[distancia.idxmin(), "COD_SETOR"], "NUMERO_PROXIMO"

    return setores.mode()[0], "SETOR_MAIS_COMUM"

def main(caminho_cnefe, caminho_busca):
    busca = pd.read_csv(caminho_busca, sep=";", dtype=str)
    busca["municipio"] = busca["consulta_municipio"].str[:6]

    print("Lendo o CNEFE (cerca de 1 a 2 minutos)...")
    cnefe = carregar_cnefe(caminho_cnefe, set(busca["municipio"]))
    print(f"{len(cnefe):,} endereços do CNEFE nos municípios da busca")

    nomes = cnefe["rua"].drop_duplicates()
    cnefe["rua_padrao"] = cnefe["rua"].map(dict(zip(nomes, nomes.map(padronizar))))

    resultados = []
    for _, linha in busca.iterrows():
        logradouro = padronizar(linha["consulta_logradouro"])
        rua_buscada = tirar_tipo(logradouro)
        tipo_buscado = logradouro.split()[0] if logradouro else ""
        cep = str(linha["consulta_cep"])
        numero = ler_numero(linha["consulta_numero"])
        cidade = cnefe[cnefe["municipio"] == linha["municipio"]]
        ruas_da_cidade = cidade["rua_padrao"].unique()
        melhor = process.extractOne(rua_buscada, ruas_da_cidade, scorer=fuzz.token_sort_ratio)

        if melhor is None or melhor[1] < NOTA_MINIMA:
            resultados.append({"setor": "NAO_ENCONTRADO", "status": "NAO_ENCONTRADO",
                               "metodo": "", "rua_cnefe": "", "nota": melhor[1] if melhor else 0})
            continue

        rua_encontrada, nota, _ = melhor
        enderecos_da_rua = cidade[cidade["rua_padrao"] == rua_encontrada]
        enderecos_da_rua = preferir(enderecos_da_rua, enderecos_da_rua["tipo"] == tipo_buscado)
        if not cep.endswith("000"):
            enderecos_da_rua = preferir(enderecos_da_rua, enderecos_da_rua["CEP"] == cep)
        setor, metodo = escolher_setor(enderecos_da_rua, numero)

        ambiguo = metodo == "SETOR_MAIS_COMUM"
        resultados.append({"setor": setor, "status": "AMBIGUO" if ambiguo else "ENCONTRADO",
                           "metodo": metodo, "rua_cnefe": rua_encontrada, "nota": round(nota)})

    saida = pd.concat([busca.drop(columns="municipio"), pd.DataFrame(resultados)], axis=1)
    saida.to_csv("resultado_simples.csv", sep=";", index=False)
    print(saida["status"].value_counts().to_string())
    print("Resultado salvo em resultado_simples.csv")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
