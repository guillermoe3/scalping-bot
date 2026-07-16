# ma-calibracion

## Pre-registro

- rol: M2 P/MA (replica de Detzel et al. 2021) — estudio de adopcion (spec 2026-07-15)
- datos: klines 1d SPOT Binance, 2017-08 -> mes corriente exclusivo, BTC+ETH
- senal: P(t)/MA_n(close), n in {10,20,50,100}; long si ratio > 1, flat si <= 1 (sin banda muerta); la posicion decidida al cierre de t se aplica al retorno de t+1
- split: calibracion 2017-08 -> 2023-12; verificacion 2024-01 -> presente (sellada); corte_ms=1704067200000
- burn_in: en verificacion, los 100 dias previos al corte solo alimentan la senal
- descriptivo: contraste de quintiles del ratio (quintil alto vs bajo, forward 1/7/14d) DENTRO de cada ventana — SOLO descriptivo
- umbral_adopcion: por celda de estrategia de BTC, en calibracion Y verificacion por separado (verificacion entera, sin subventanas): Sharpe estrategia > Sharpe buy-and-hold, Y max drawdown estrategia < buy-and-hold, Y media de r_strat > 0, Y mediana de r_strat sobre los dias con posicion > 0. 'Casi' = NO PASA. Solo BTC adopta/veta; ETH robustez.
- regla_fragilidad: si M1 pasa y M2 falla (o viceversa) en celdas economicamente equivalentes, se reporta como fragilidad de especificacion — no se elige la mejor
- criterio_abandono: si ninguna celda de M1 ni M2 pasa en BTC -> se congela la busqueda de senal (firmado 2026-07-15)

Celdas miradas: 56

## Resultados

```json
{
  "BTCUSDT": {
    "buy_and_hold": {
      "n_dias": 2327,
      "sharpe": 0.8613042757956989,
      "max_drawdown": 0.8318705353076483,
      "media": 0.0017390167117820104
    },
    "estrategia": {
      "10": {
        "n_dias": 2327,
        "n_dias_en_posicion": 1239,
        "sharpe": 0.9821561555013318,
        "max_drawdown": 0.6706068172847645,
        "media": 0.0013402179419543469,
        "mediana_en_posicion": -0.0002931462953200681
      },
      "20": {
        "n_dias": 2327,
        "n_dias_en_posicion": 1221,
        "sharpe": 1.138496227753168,
        "max_drawdown": 0.6396446092098067,
        "media": 0.0015187401655202405,
        "mediana_en_posicion": 9.442208382015593e-05
      },
      "50": {
        "n_dias": 2327,
        "n_dias_en_posicion": 1176,
        "sharpe": 1.414741431594266,
        "max_drawdown": 0.6258890519207934,
        "media": 0.0019480249875069465,
        "mediana_en_posicion": 0.0014082465592845095
      },
      "100": {
        "n_dias": 2327,
        "n_dias_en_posicion": 1147,
        "sharpe": 1.1151156676629805,
        "max_drawdown": 0.6333711317577119,
        "media": 0.0015271914989066278,
        "mediana_en_posicion": 0.0012939826402011967
      }
    },
    "quintiles": {
      "10": {
        "1d": {
          "q_bajo": {
            "n": 463,
            "media": 0.0011313301828028372,
            "mediana": 0.0036536094572238768,
            "hit_rate": 0.5529157667386609
          },
          "q_alto": {
            "n": 463,
            "media": 0.006544830782303178,
            "mediana": 0.0017929468724360194,
            "hit_rate": 0.5226781857451404
          }
        },
        "7d": {
          "q_bajo": {
            "n": 462,
            "media": 0.010737430521667049,
            "mediana": 0.008824549588310731,
            "hit_rate": 0.5411255411255411
          },
          "q_alto": {
            "n": 462,
            "media": 0.03479452107169926,
            "mediana": 0.018593284844807094,
            "hit_rate": 0.5714285714285714
          }
        },
        "14d": {
          "q_bajo": {
            "n": 461,
            "media": 0.017257847209550713,
            "mediana": -0.0002785812305036463,
            "hit_rate": 0.49891540130151846
          },
          "q_alto": {
            "n": 461,
            "media": 0.06367584883150162,
            "mediana": 0.049136678238422965,
            "hit_rate": 0.613882863340564
          }
        }
      },
      "20": {
        "1d": {
          "q_bajo": {
            "n": 461,
            "media": 0.0010663515212025645,
            "mediana": 0.0033086110646816306,
            "hit_rate": 0.5466377440347071
          },
          "q_alto": {
            "n": 461,
            "media": 0.005321860307500075,
            "mediana": 0.0008109090753829711,
            "hit_rate": 0.5075921908893709
          }
        },
        "7d": {
          "q_bajo": {
            "n": 460,
            "media": 0.007708070018172911,
            "mediana": 0.006340229946857474,
            "hit_rate": 0.5282608695652173
          },
          "q_alto": {
            "n": 460,
            "media": 0.035127122201373887,
            "mediana": 0.024281137508345214,
            "hit_rate": 0.6152173913043478
          }
        },
        "14d": {
          "q_bajo": {
            "n": 459,
            "media": 0.015220269331404199,
            "mediana": 0.006058230785953237,
            "hit_rate": 0.5294117647058824
          },
          "q_alto": {
            "n": 459,
            "media": 0.06590377884662078,
            "mediana": 0.04178178879747176,
            "hit_rate": 0.6274509803921569
          }
        }
      },
      "50": {
        "1d": {
          "q_bajo": {
            "n": 455,
            "media": 0.00043351154022445564,
            "mediana": 0.002168324249680379,
            "hit_rate": 0.5252747252747253
          },
          "q_alto": {
            "n": 455,
            "media": 0.003980257175852004,
            "mediana": 0.0012453901007426467,
            "hit_rate": 0.512087912087912
          }
        },
        "7d": {
          "q_bajo": {
            "n": 454,
            "media": 0.00617837483706168,
            "mediana": 0.004679512364545327,
            "hit_rate": 0.5220264317180616
          },
          "q_alto": {
            "n": 454,
            "media": 0.03631383207821697,
            "mediana": 0.020300539764867565,
            "hit_rate": 0.6013215859030837
          }
        },
        "14d": {
          "q_bajo": {
            "n": 453,
            "media": 0.005639486119465489,
            "mediana": 0.004237110483199364,
            "hit_rate": 0.5121412803532008
          },
          "q_alto": {
            "n": 453,
            "media": 0.07562547884680808,
            "mediana": 0.045610534939060886,
            "hit_rate": 0.6644591611479028
          }
        }
      },
      "100": {
        "1d": {
          "q_bajo": {
            "n": 445,
            "media": 0.0014017588684505267,
            "mediana": 0.0005650260706234225,
            "hit_rate": 0.5101123595505618
          },
          "q_alto": {
            "n": 445,
            "media": 0.004436473340194158,
            "mediana": 0.002233892089605101,
            "hit_rate": 0.5325842696629214
          }
        },
        "7d": {
          "q_bajo": {
            "n": 444,
            "media": 0.015532089660131275,
            "mediana": 0.008439193456259576,
            "hit_rate": 0.5337837837837838
          },
          "q_alto": {
            "n": 444,
            "media": 0.03852644604783186,
            "mediana": 0.018772274347920125,
            "hit_rate": 0.5833333333333334
          }
        },
        "14d": {
          "q_bajo": {
            "n": 443,
            "media": 0.021077418758293904,
            "mediana": 0.013086468257009437,
            "hit_rate": 0.5440180586907449
          },
          "q_alto": {
            "n": 443,
            "media": 0.08033449215312795,
            "mediana": 0.035084080810041746,
            "hit_rate": 0.6252821670428894
          }
        }
      }
    }
  },
  "ETHUSDT": {
    "buy_and_hold": {
      "n_dias": 2327,
      "sharpe": 0.8149400403425237,
      "max_drawdown": 0.9396550481981527,
      "media": 0.0020775085698512123
    },
    "estrategia": {
      "10": {
        "n_dias": 2327,
        "n_dias_en_posicion": 1224,
        "sharpe": 0.9246122060546215,
        "max_drawdown": 0.5923860111724518,
        "media": 0.001601843881635478,
        "mediana_en_posicion": -0.0011377426778713673
      },
      "20": {
        "n_dias": 2327,
        "n_dias_en_posicion": 1180,
        "sharpe": 1.1674794022046926,
        "max_drawdown": 0.5955887534368265,
        "media": 0.0020418123340389025,
        "mediana_en_posicion": 0.0003572872518030623
      },
      "50": {
        "n_dias": 2327,
        "n_dias_en_posicion": 1195,
        "sharpe": 1.0960517754272965,
        "max_drawdown": 0.6384186141946026,
        "media": 0.0019367714622041496,
        "mediana_en_posicion": 0.001492760113449787
      },
      "100": {
        "n_dias": 2327,
        "n_dias_en_posicion": 1226,
        "sharpe": 0.9059204231034212,
        "max_drawdown": 0.7362493125754106,
        "media": 0.0016793234599334537,
        "mediana_en_posicion": 0.0017837348966006639
      }
    },
    "quintiles": {
      "10": {
        "1d": {
          "q_bajo": {
            "n": 463,
            "media": 0.0006273428564214457,
            "mediana": 0.004970603955104259,
            "hit_rate": 0.5529157667386609
          },
          "q_alto": {
            "n": 463,
            "media": 0.0049966035794168735,
            "mediana": 0.0020889151264700946,
            "hit_rate": 0.5161987041036717
          }
        },
        "7d": {
          "q_bajo": {
            "n": 462,
            "media": 0.009789259598666486,
            "mediana": 0.011070459322919373,
            "hit_rate": 0.5432900432900433
          },
          "q_alto": {
            "n": 462,
            "media": 0.031460478019671376,
            "mediana": 0.008943754378327843,
            "hit_rate": 0.5173160173160173
          }
        },
        "14d": {
          "q_bajo": {
            "n": 461,
            "media": 0.013297843691179912,
            "mediana": 0.0014053838134857237,
            "hit_rate": 0.5010845986984815
          },
          "q_alto": {
            "n": 461,
            "media": 0.05451222533070779,
            "mediana": 0.04364624505928861,
            "hit_rate": 0.5900216919739696
          }
        }
      },
      "20": {
        "1d": {
          "q_bajo": {
            "n": 461,
            "media": -0.0010656768582164929,
            "mediana": 0.0015631280425170574,
            "hit_rate": 0.5184381778741866
          },
          "q_alto": {
            "n": 461,
            "media": 0.007149391374572547,
            "mediana": 0.0022086527218396386,
            "hit_rate": 0.527114967462039
          }
        },
        "7d": {
          "q_bajo": {
            "n": 460,
            "media": 0.0022599667533876474,
            "mediana": -0.0020087692720603687,
            "hit_rate": 0.4956521739130435
          },
          "q_alto": {
            "n": 460,
            "media": 0.0353912474794345,
            "mediana": 0.016692494250478328,
            "hit_rate": 0.5521739130434783
          }
        },
        "14d": {
          "q_bajo": {
            "n": 459,
            "media": 0.0003952769651815563,
            "mediana": -0.004222421922125323,
            "hit_rate": 0.4880174291938998
          },
          "q_alto": {
            "n": 459,
            "media": 0.05413200449323932,
            "mediana": 0.03743162611495725,
            "hit_rate": 0.5947712418300654
          }
        }
      },
      "50": {
        "1d": {
          "q_bajo": {
            "n": 455,
            "media": 0.0008988359709940672,
            "mediana": 0.0008052502315093957,
            "hit_rate": 0.5142857142857142
          },
          "q_alto": {
            "n": 455,
            "media": 0.004028036739861345,
            "mediana": 0.0009396623856136634,
            "hit_rate": 0.512087912087912
          }
        },
        "7d": {
          "q_bajo": {
            "n": 454,
            "media": -0.0002605560043839338,
            "mediana": -0.002057669646966653,
            "hit_rate": 0.4955947136563877
          },
          "q_alto": {
            "n": 454,
            "media": 0.030885028769626198,
            "mediana": 0.009702915517210725,
            "hit_rate": 0.5286343612334802
          }
        },
        "14d": {
          "q_bajo": {
            "n": 453,
            "media": 0.007364152711928875,
            "mediana": -0.008963118969486228,
            "hit_rate": 0.4768211920529801
          },
          "q_alto": {
            "n": 453,
            "media": 0.057795073781523564,
            "mediana": 0.02063537402012123,
            "hit_rate": 0.565121412803532
          }
        }
      },
      "100": {
        "1d": {
          "q_bajo": {
            "n": 445,
            "media": 0.002657426106615675,
            "mediana": 0.000629544524536462,
            "hit_rate": 0.5101123595505618
          },
          "q_alto": {
            "n": 445,
            "media": 0.0050864905017303135,
            "mediana": 0.0037627358836321953,
            "hit_rate": 0.5460674157303371
          }
        },
        "7d": {
          "q_bajo": {
            "n": 444,
            "media": 0.013010964511879641,
            "mediana": 0.011522401534619777,
            "hit_rate": 0.5337837837837838
          },
          "q_alto": {
            "n": 444,
            "media": 0.03483728652777849,
            "mediana": 0.015118440713112751,
            "hit_rate": 0.5427927927927928
          }
        },
        "14d": {
          "q_bajo": {
            "n": 443,
            "media": 0.0329619310343029,
            "mediana": 0.022266133307629304,
            "hit_rate": 0.5327313769751693
          },
          "q_alto": {
            "n": 443,
            "media": 0.07073536363334203,
            "mediana": 0.03291699494832457,
            "hit_rate": 0.5598194130925508
          }
        }
      }
    }
  }
}
```
