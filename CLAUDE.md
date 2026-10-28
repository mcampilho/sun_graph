# sun_graph — gráficos, mapas e animação sobre a luz do Sol

Scripts Python independentes, cada um gera uma imagem ou vídeo. Repositório git (ramo `master`),
licença MIT (`LICENSE`). Commit e push só com aprovação explícita do utilizador.
Neste PC usa-se `python3` (não `python`).

| Script | O que gera | Saída típica |
|---|---|---|
| `solar_graph.py` | Gráfico anual de luz solar de um local: dia, crepúsculos civil/náutico/astronómico, noite, meio-dia e meia-noite solares, faixa detalhada de um dia. Elevação do Sol calculada minuto a minuto (funciona em latitudes polares). Textos em inglês ou português (`--lang en/pt`). Comparação de horários: `--mark HH:MM` (linhas tracejadas, repetível), `--dst legal/off/on` (hora de verão real, desligada, ou simulada onde não existe — regra europeia a norte, out→abr a sul; ver `simulated_dst`) e `--shift ±H` (muda a hora padrão); tudo em `local_offsets`, e a nota "Simulação" aparece a vermelho por baixo do título. Antes chamava-se `grafico_sol.py` (em português); sem estas opções e com `--lang pt` gera imagens idênticas às do original. | `images/solar_graph_tromso_{en,pt}.png`, `images/solar_graph_lisboa_{en,pt}.png` (`--day 06-21 --mark 08:30 --mark 17:30 --dst off`) |
| `solar_time_map.py` | Mapa mundial "hora solar média − hora oficial" (vermelho = relógio adiantado, azul = atrasado). Textos e nomes de países em 10 idiomas (`--lang`; `--lang pt` para português). Substituiu a versão original só em português, `mapa_hora_solar.py`, já apagada. | `solar_time_map.png` (padrão), `equal-earth.png`, `miller.png`, `mapa_pt_robinson.png`, `exemplos_zh_ar_ja_ru.png` |
| `earth_moon_sun.py` | Animação Terra · Lua · Sol (3 atos: rotação de 24 h, mês sinódico com eclipses e órbita inclinada da Lua, ano em órbita kepleriana com estações). Ray tracer em numpy. Textos `--lang en/pt`. Antes chamava-se `earth_moon_sun_v2.py`; a versão anterior, mais simples, ficou em `earth_moon_sun_old.py` (a apagar). | `earth_moon_sun.mp4` (padrão); `earth_moon_sun_v2.mp4` é o vídeo completo em português desta versão, e o `earth_moon_sun.mp4` que existe é da versão antiga |

Documentação para partilhar: `README.md` (inglês) e `README.pt.md` (português europeu), com ligações
entre si; manter os dois sincronizados ao mudar opções ou comportamento. As imagens dos READMEs estão em
`images/` (uma versão `_en` e outra `_pt` de cada): gráfico de Tromsø (`--year 2026 --day 12-21`),
mapa Equal Earth e um frame do eclipse solar da animação (frame 36 de
`--scenes 2 --step 15 --lang en`; frame 900 de `earth_moon_sun_v2.mp4`, que está em português).

`solar_time_map_reference.png` é um mapa de referência (projeção Miller, de outra fonte) para comparar
os fusos e os rótulos de `solar_time_map.png`. `sun_graph_output.png`, `tromso_5_bibliotecas.png` e
`orig_all.png` vêm de experiências antigas (comparação de bibliotecas como astral, ephem, skyfield) cujo
script já não está na pasta; não são gerados por nenhum script atual.

## Comandos

```bash
# solar_graph.py
pip install numpy matplotlib geopy timezonefinder tzdata
python3 solar_graph.py "Lisboa, Portugal" --lang pt --output lisboa.png
python3 solar_graph.py --lat 69.65 --lon 18.96 --name Tromsø --tz Europe/Oslo --day 12-21

# solar_time_map.py
pip install numpy scipy matplotlib cartopy geopandas rasterio shapely tzdata
python3 solar_time_map.py --lang en                       # gera solar_time_map.png (~40 s)
python3 solar_time_map.py -p robinson --lang pt --output mapa.png
python3 solar_time_map.py -p mercator --date 2026-07-01   # com hora de verão

# earth_moon_sun
pip install numpy pillow imageio imageio-ffmpeg
python3 earth_moon_sun.py --step 10 --output preview.mp4   # pré-visualização rápida
python3 earth_moon_sun.py --scenes 2 --lang en
```

## Como `solar_time_map.py` atribui os fusos

- Os fusos vêm de `timezones-with-oceans-now` (timezone-boundary-builder). Cada `tzid` é convertido
  num desvio com `zoneinfo` (pacote `tzdata` no Windows): sem `--date`, o menor desvio entre janeiro
  e julho (hora padrão); com `--date`, o desvio legal nesse dia. Os nomes `Etc/GMT+N` têm o sinal
  POSIX invertido (`Etc/GMT+2` = UTC−2); o `zoneinfo` já trata disso.
- No mar, esse ficheiro só tem fusos náuticos `Etc/GMT±N`: faixas de 15° definidas pela longitude.
  Por isso, em `compute_grid`, cada fuso civil é estendido para o mar até `--sea-margin` graus
  (padrão 1,5°) da costa, por vizinho mais próximo (`scipy.ndimage.distance_transform_edt`, com
  continuidade nos 180°). As faixas náuticas só preenchem o mar aberto. Sem isto, as linhas e os
  rótulos dos Açores (−1), da Islândia (0), de Kiribati (+14), Samoa/Tonga/Tokelau (+13), Chatham
  (+12¾) etc. ficavam com o valor da faixa à volta.
- As linhas e os rótulos de desvio são desenhados a partir dessa grelha vetorizada
  (`rasterio.features.shapes`) e unida por desvio; as cores em terra usam o desvio do fuso civil.
- Ordem dos rótulos (o primeiro a ocupar o lugar ganha): nomes dos países principais (LABELRANK 1–2),
  desvios das regiões pequenas (< 200 graus², ilhas com fuso próprio), restantes nomes, desvios das
  regiões grandes. Cada rótulo de desvio tenta vários pontos dentro da região (`label_points`).

## Notas

- Os mapas e a animação descarregam dados na primeira execução (fusos: timezone-boundary-builder;
  terras/países/cidades: Natural Earth) para `~/.cache/<nome_do_script>` (opção `--cache`).
- Verificar os mapas visualmente; para os ver no painel do browser, servir a pasta com
  `python3 -m http.server` (o `file://` está bloqueado).
- Renderizar a animação completa demora; usa `--step` e `--scenes` para iterar.
- Tamanhos e distâncias na animação não estão à escala, de propósito.
- O projeto vai ser partilhado: código, comentários, nomes de variáveis e opções em inglês
  (`--output`, `--lang`, `--year` ...); os textos das imagens são traduzidos via `--lang`
  (por omissão, o idioma do sistema).
- Árabe no matplotlib < 3.11 precisa de `arabic-reshaper` e `python-bidi`; chinês/japonês precisam de uma fonte CJK.
