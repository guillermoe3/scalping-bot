# momentum-calibracion

## Pre-registro

- rol: M1 TSMOM — estudio de adopcion (spec 2026-07-15)
- datos: klines 1d SPOT Binance, 2017-08 -> mes corriente exclusivo, BTC+ETH
- senal: sign(ret[t-k, t]), k in {7,14,28,56,90}; la posicion decidida al cierre de t se aplica al retorno de t+1
- variantes: long_short (pos=senal) y long_flat (pos=max(senal,0)); posiciones 0 hasta completar lookback
- split: calibracion 2017-08 -> 2023-12; verificacion 2024-01 -> presente (sellada); corte_ms=1704067200000
- burn_in: en verificacion, los 90 dias previos al corte solo alimentan la senal
- descriptivo: retorno forward 1/7/14/28d firmado, por lado — SOLO descriptivo (ventanas superpuestas, errores autocorrelacionados)
- umbral_adopcion: por celda de estrategia de BTC, en calibracion Y verificacion por separado (verificacion entera, sin subventanas): Sharpe estrategia > Sharpe buy-and-hold, Y max drawdown estrategia < buy-and-hold, Y media de r_strat > 0, Y mediana de r_strat sobre los dias con posicion > 0. 'Casi' = NO PASA. Solo BTC adopta/veta; ETH robustez.
- criterio_abandono: si ninguna celda de M1 ni M2 pasa en BTC -> se congela la busqueda de senal (firmado 2026-07-15)
- n_efectivo: advertencia pre-registrada: BTC tiene ~4 ciclos de mercado independientes; el n efectivo de regimenes es 4, no ~3250 dias

Celdas miradas: 100

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
      "7": {
        "long_short": {
          "n_dias": 2327,
          "n_dias_en_posicion": 2320,
          "sharpe": 0.5035999966466517,
          "max_drawdown": 0.7610771158738445,
          "media": 0.0010167387662526953,
          "mediana_en_posicion": -0.0006921352753491705
        },
        "long_flat": {
          "n_dias": 2327,
          "n_dias_en_posicion": 1235,
          "sharpe": 1.00456848815946,
          "max_drawdown": 0.6351940999212424,
          "media": 0.0013757974976032078,
          "mediana_en_posicion": -8.287892560088217e-05
        }
      },
      "14": {
        "long_short": {
          "n_dias": 2327,
          "n_dias_en_posicion": 2313,
          "sharpe": 0.8813298886096587,
          "max_drawdown": 0.6534659026078381,
          "media": 0.0017770184537266396,
          "mediana_en_posicion": 0.0003088750210802349
        },
        "long_flat": {
          "n_dias": 2327,
          "n_dias_en_posicion": 1250,
          "sharpe": 1.2609770593750584,
          "max_drawdown": 0.6553363166297628,
          "media": 0.0017360556406718546,
          "mediana_en_posicion": 0.0010101904377421977
        }
      },
      "28": {
        "long_short": {
          "n_dias": 2327,
          "n_dias_en_posicion": 2299,
          "sharpe": 0.9674768765500168,
          "max_drawdown": 0.8377052110346885,
          "media": 0.0019302381157173722,
          "mediana_en_posicion": 9.442208382015593e-05
        },
        "long_flat": {
          "n_dias": 2327,
          "n_dias_en_posicion": 1250,
          "sharpe": 1.3404403405250656,
          "max_drawdown": 0.7443733832209671,
          "media": 0.001888826274725306,
          "mediana_en_posicion": 0.0009614605258503328
        }
      },
      "56": {
        "long_short": {
          "n_dias": 2327,
          "n_dias_en_posicion": 2271,
          "sharpe": 1.1078341244910406,
          "max_drawdown": 0.7178129527806862,
          "media": 0.002183444043289553,
          "mediana_en_posicion": 0.0011195381620978662
        },
        "long_flat": {
          "n_dias": 2327,
          "n_dias_en_posicion": 1232,
          "sharpe": 1.3351420705219732,
          "max_drawdown": 0.650991572235986,
          "media": 0.0018930674863031,
          "mediana_en_posicion": 0.0016763042280822926
        }
      },
      "90": {
        "long_short": {
          "n_dias": 2327,
          "n_dias_en_posicion": 2237,
          "sharpe": 0.492951352623142,
          "max_drawdown": 0.8868040823522256,
          "media": 0.0009620356701286377,
          "mediana_en_posicion": 0.0008109090753829484
        },
        "long_flat": {
          "n_dias": 2327,
          "n_dias_en_posicion": 1196,
          "sharpe": 0.8141879555009433,
          "max_drawdown": 0.6603448415228742,
          "media": 0.0012128085477403692,
          "mediana_en_posicion": 0.0012805276542928734
        }
      }
    },
    "descriptivo": {
      "7": {
        "1d": {
          "long": {
            "n": 1235,
            "media": 0.0025922921270628875,
            "mediana": -8.287892560085624e-05,
            "hit_rate": 0.497165991902834
          },
          "short": {
            "n": 1085,
            "media": -0.0007700734265922984,
            "mediana": -0.001743439163149305,
            "hit_rate": 0.4682027649769585
          }
        },
        "7d": {
          "long": {
            "n": 1233,
            "media": 0.015722954687592477,
            "mediana": 0.004605825242718496,
            "hit_rate": 0.527169505271695
          },
          "short": {
            "n": 1081,
            "media": -0.008510300455727815,
            "mediana": -0.007195765207629771,
            "hit_rate": 0.4653098982423682
          }
        },
        "14d": {
          "long": {
            "n": 1226,
            "media": 0.033702792204412316,
            "mediana": 0.016160306337588103,
            "hit_rate": 0.5505709624796085
          },
          "short": {
            "n": 1081,
            "media": -0.01633344562413527,
            "mediana": -0.004712079938496316,
            "hit_rate": 0.47363552266419984
          }
        },
        "28d": {
          "long": {
            "n": 1219,
            "media": 0.06996656107389024,
            "mediana": 0.039985143064136516,
            "hit_rate": 0.5701394585726005
          },
          "short": {
            "n": 1074,
            "media": -0.037530563662499565,
            "mediana": -0.004714995824414089,
            "hit_rate": 0.48324022346368717
          }
        }
      },
      "14": {
        "1d": {
          "long": {
            "n": 1250,
            "media": 0.003231841180674727,
            "mediana": 0.0010101904377421234,
            "hit_rate": 0.5184
          },
          "short": {
            "n": 1063,
            "media": 8.967118154137971e-05,
            "mediana": -0.00030570063873680656,
            "hit_rate": 0.4929444967074318
          }
        },
        "7d": {
          "long": {
            "n": 1246,
            "media": 0.020161890255664516,
            "mediana": 0.010458385148532517,
            "hit_rate": 0.5537720706260032
          },
          "short": {
            "n": 1061,
            "media": -0.003074636600545307,
            "mediana": -0.00071215190107561,
            "hit_rate": 0.49764373232799247
          }
        },
        "14d": {
          "long": {
            "n": 1244,
            "media": 0.037798903901911214,
            "mediana": 0.021676781698897012,
            "hit_rate": 0.567524115755627
          },
          "short": {
            "n": 1056,
            "media": -0.011546916101408596,
            "mediana": -0.000910583028352552,
            "hit_rate": 0.49242424242424243
          }
        },
        "28d": {
          "long": {
            "n": 1230,
            "media": 0.08150708707191015,
            "mediana": 0.04467328019038317,
            "hit_rate": 0.5780487804878048
          },
          "short": {
            "n": 1056,
            "media": -0.02489172161459119,
            "mediana": -0.0037699426136686524,
            "hit_rate": 0.4895833333333333
          }
        }
      },
      "28": {
        "1d": {
          "long": {
            "n": 1250,
            "media": 0.0035162389930286308,
            "mediana": 0.0009614605258503846,
            "hit_rate": 0.5144
          },
          "short": {
            "n": 1049,
            "media": 9.186401714827245e-05,
            "mediana": -0.0005650260706234225,
            "hit_rate": 0.4871306005719733
          }
        },
        "7d": {
          "long": {
            "n": 1244,
            "media": 0.023154542272201123,
            "mediana": 0.012705690127424805,
            "hit_rate": 0.5627009646302251
          },
          "short": {
            "n": 1049,
            "media": -0.0007630487669736327,
            "mediana": 0.0003198724148699245,
            "hit_rate": 0.5023832221163013
          }
        },
        "14d": {
          "long": {
            "n": 1237,
            "media": 0.04321605144391399,
            "mediana": 0.021035472691938797,
            "hit_rate": 0.5723524656426839
          },
          "short": {
            "n": 1049,
            "media": -0.007275606023310621,
            "mediana": -0.002076178537030139,
            "hit_rate": 0.4918970448045758
          }
        },
        "28d": {
          "long": {
            "n": 1223,
            "media": 0.08811547237217326,
            "mediana": 0.038864153201675536,
            "hit_rate": 0.5682747342600164
          },
          "short": {
            "n": 1049,
            "media": -0.01764091716865385,
            "mediana": -0.009192056784588775,
            "hit_rate": 0.4775977121067683
          }
        }
      },
      "56": {
        "1d": {
          "long": {
            "n": 1232,
            "media": 0.003575623409600094,
            "mediana": 0.0016763042280822263,
            "hit_rate": 0.5324675324675324
          },
          "short": {
            "n": 1039,
            "media": 0.0006503428759455958,
            "mediana": 0.00025055546822251096,
            "hit_rate": 0.5101058710298364
          }
        },
        "7d": {
          "long": {
            "n": 1226,
            "media": 0.0208212516388767,
            "mediana": 0.010628318878151688,
            "hit_rate": 0.5505709624796085
          },
          "short": {
            "n": 1039,
            "media": -0.0008655863296026206,
            "mediana": -0.0006133359337672823,
            "hit_rate": 0.4966313763233879
          }
        },
        "14d": {
          "long": {
            "n": 1219,
            "media": 0.036593660364127804,
            "mediana": 0.012718441221322157,
            "hit_rate": 0.5397867104183757
          },
          "short": {
            "n": 1039,
            "media": -0.009475038988362989,
            "mediana": -0.007945532310238885,
            "hit_rate": 0.465832531280077
          }
        },
        "28d": {
          "long": {
            "n": 1205,
            "media": 0.07272991432730026,
            "mediana": 0.01846468534463219,
            "hit_rate": 0.5327800829875519
          },
          "short": {
            "n": 1039,
            "media": -0.023392628566514268,
            "mediana": -0.015526393941643792,
            "hit_rate": 0.44850818094321465
          }
        }
      },
      "90": {
        "1d": {
          "long": {
            "n": 1196,
            "media": 0.0023597035874513717,
            "mediana": 0.001280527654292876,
            "hit_rate": 0.5267558528428093
          },
          "short": {
            "n": 1041,
            "media": -0.0005605653085518738,
            "mediana": 0.00013521805068353437,
            "hit_rate": 0.5043227665706052
          }
        },
        "7d": {
          "long": {
            "n": 1190,
            "media": 0.01620658917900575,
            "mediana": 0.005677013235095922,
            "hit_rate": 0.5369747899159664
          },
          "short": {
            "n": 1041,
            "media": -0.004308982051498746,
            "mediana": -0.0034774214925088896,
            "hit_rate": 0.48703170028818443
          }
        },
        "14d": {
          "long": {
            "n": 1183,
            "media": 0.031752390766789346,
            "mediana": 0.009909775813506097,
            "hit_rate": 0.5376162299239222
          },
          "short": {
            "n": 1041,
            "media": -0.010568222276058433,
            "mediana": -0.006058230785953237,
            "hit_rate": 0.47646493756003844
          }
        },
        "28d": {
          "long": {
            "n": 1169,
            "media": 0.06119352011912101,
            "mediana": 0.016924499646396137,
            "hit_rate": 0.5286569717707442
          },
          "short": {
            "n": 1041,
            "media": -0.01967511363176243,
            "mediana": -0.012381848905873474,
            "hit_rate": 0.45917387127761766
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
      "7": {
        "long_short": {
          "n_dias": 2327,
          "n_dias_en_posicion": 2320,
          "sharpe": 0.9479981081798696,
          "max_drawdown": 0.6853023949352324,
          "media": 0.0024135630420946278,
          "mediana_en_posicion": -0.0006125573443664933
        },
        "long_flat": {
          "n_dias": 2327,
          "n_dias_en_posicion": 1216,
          "sharpe": 1.289882679061995,
          "max_drawdown": 0.5820238127700563,
          "media": 0.002229678231898418,
          "mediana_en_posicion": 0.00010363847718275476
        }
      },
      "14": {
        "long_short": {
          "n_dias": 2327,
          "n_dias_en_posicion": 2313,
          "sharpe": 0.6792634714051383,
          "max_drawdown": 0.7704381932881713,
          "media": 0.0017287114946914278,
          "mediana_en_posicion": 0.00019138755980852018
        },
        "long_flat": {
          "n_dias": 2327,
          "n_dias_en_posicion": 1223,
          "sharpe": 1.017949954606431,
          "max_drawdown": 0.7483924559691054,
          "media": 0.00184880685206843,
          "mediana_en_posicion": 0.00048290224247726776
        }
      },
      "28": {
        "long_short": {
          "n_dias": 2327,
          "n_dias_en_posicion": 2299,
          "sharpe": 0.6335662444885976,
          "max_drawdown": 0.7768357514158949,
          "media": 0.0015947888296735688,
          "mediana_en_posicion": 0.00048290224247726776
        },
        "long_flat": {
          "n_dias": 2327,
          "n_dias_en_posicion": 1239,
          "sharpe": 1.0153013221516285,
          "max_drawdown": 0.6512660440180003,
          "media": 0.0018922805057252526,
          "mediana_en_posicion": 0.0012692456266210073
        }
      },
      "56": {
        "long_short": {
          "n_dias": 2327,
          "n_dias_en_posicion": 2271,
          "sharpe": 0.8455483866288972,
          "max_drawdown": 0.879203760290823,
          "media": 0.002110095050286696,
          "mediana_en_posicion": 0.001003188478028827
        },
        "long_flat": {
          "n_dias": 2327,
          "n_dias_en_posicion": 1269,
          "sharpe": 1.0722350523716977,
          "max_drawdown": 0.6711653393494028,
          "media": 0.002066870911455996,
          "mediana_en_posicion": 0.0017192459363277734
        }
      },
      "90": {
        "long_short": {
          "n_dias": 2327,
          "n_dias_en_posicion": 2237,
          "sharpe": 0.4397428500547513,
          "max_drawdown": 0.936572335700738,
          "media": 0.0010925124551929848,
          "mediana_en_posicion": 0.00048480827746355537
        },
        "long_flat": {
          "n_dias": 2327,
          "n_dias_en_posicion": 1235,
          "sharpe": 0.8065639297519953,
          "max_drawdown": 0.7835005695100565,
          "media": 0.0015338344483816874,
          "mediana_en_posicion": 0.0012692456266210073
        }
      }
    },
    "descriptivo": {
      "7": {
        "1d": {
          "long": {
            "n": 1216,
            "media": 0.004266826682259554,
            "mediana": 0.00010363847718277295,
            "hit_rate": 0.5016447368421053
          },
          "short": {
            "n": 1104,
            "media": 0.00038759053743349543,
            "mediana": -0.0015685258409173484,
            "hit_rate": 0.48097826086956524
          }
        },
        "7d": {
          "long": {
            "n": 1212,
            "media": 0.019219327553680245,
            "mediana": 0.003902475772645796,
            "hit_rate": 0.5132013201320133
          },
          "short": {
            "n": 1102,
            "media": -0.008955177498329242,
            "mediana": -0.006230190405047657,
            "hit_rate": 0.4664246823956443
          }
        },
        "14d": {
          "long": {
            "n": 1209,
            "media": 0.036969963230380466,
            "mediana": 0.013706039527915182,
            "hit_rate": 0.5401157981803143
          },
          "short": {
            "n": 1098,
            "media": -0.022151195248756694,
            "mediana": -0.00512661156678571,
            "hit_rate": 0.4854280510018215
          }
        },
        "28d": {
          "long": {
            "n": 1201,
            "media": 0.0770422198034782,
            "mediana": 0.03719427021993368,
            "hit_rate": 0.5653621981681932
          },
          "short": {
            "n": 1092,
            "media": -0.05189705889635508,
            "mediana": -0.00499436663333298,
            "hit_rate": 0.48626373626373626
          }
        }
      },
      "14": {
        "1d": {
          "long": {
            "n": 1223,
            "media": 0.003517721622864462,
            "mediana": 0.00048290224247736404,
            "hit_rate": 0.5102207686017989
          },
          "short": {
            "n": 1090,
            "media": -0.0002563870611158583,
            "mediana": -0.0005925645113619965,
            "hit_rate": 0.4926605504587156
          }
        },
        "7d": {
          "long": {
            "n": 1217,
            "media": 0.0270510949844815,
            "mediana": 0.012007621073153476,
            "hit_rate": 0.5382087099424815
          },
          "short": {
            "n": 1090,
            "media": -0.00029749100613505626,
            "mediana": -0.0016324361762962395,
            "hit_rate": 0.4935779816513762
          }
        },
        "14d": {
          "long": {
            "n": 1217,
            "media": 0.051962583819876375,
            "mediana": 0.021759235024167083,
            "hit_rate": 0.5628594905505341
          },
          "short": {
            "n": 1083,
            "media": -0.006203773411395211,
            "mediana": 0.001963942347198794,
            "hit_rate": 0.5087719298245614
          }
        },
        "28d": {
          "long": {
            "n": 1203,
            "media": 0.09475972416935496,
            "mediana": 0.04310773504346794,
            "hit_rate": 0.5827098919368247
          },
          "short": {
            "n": 1083,
            "media": -0.03370792731653988,
            "mediana": 0.001204495151448468,
            "hit_rate": 0.5023084025854109
          }
        }
      },
      "28": {
        "1d": {
          "long": {
            "n": 1239,
            "media": 0.0035539440975162736,
            "mediana": 0.0012692456266209548,
            "hit_rate": 0.5173527037933817
          },
          "short": {
            "n": 1060,
            "media": -0.0006530784246908192,
            "mediana": -0.00016176012230862245,
            "hit_rate": 0.4981132075471698
          }
        },
        "7d": {
          "long": {
            "n": 1233,
            "media": 0.027327910866045826,
            "mediana": 0.012207856315619577,
            "hit_rate": 0.5442011354420113
          },
          "short": {
            "n": 1060,
            "media": -0.0011224046082971486,
            "mediana": -0.0012112748250394886,
            "hit_rate": 0.4962264150943396
          }
        },
        "14d": {
          "long": {
            "n": 1226,
            "media": 0.04963153976773203,
            "mediana": 0.017594644002944936,
            "hit_rate": 0.5619902120717781
          },
          "short": {
            "n": 1060,
            "media": -0.010354746666060004,
            "mediana": 0.0011550795829262856,
            "hit_rate": 0.5037735849056604
          }
        },
        "28d": {
          "long": {
            "n": 1212,
            "media": 0.09999765742914227,
            "mediana": 0.04673738345947136,
            "hit_rate": 0.5924092409240924
          },
          "short": {
            "n": 1060,
            "media": -0.02830920024219971,
            "mediana": 0.006761575619032299,
            "hit_rate": 0.5132075471698113
          }
        }
      },
      "56": {
        "1d": {
          "long": {
            "n": 1269,
            "media": 0.0037900777076107987,
            "mediana": 0.0017192459363278634,
            "hit_rate": 0.5232466509062254
          },
          "short": {
            "n": 1002,
            "media": 0.000100381807444152,
            "mediana": 0.0004038664519760215,
            "hit_rate": 0.5059880239520959
          }
        },
        "7d": {
          "long": {
            "n": 1263,
            "media": 0.025023419962328763,
            "mediana": 0.011692526563819835,
            "hit_rate": 0.5534441805225653
          },
          "short": {
            "n": 1002,
            "media": -0.0016396759323070106,
            "mediana": 0.003426398188397482,
            "hit_rate": 0.5199600798403193
          }
        },
        "14d": {
          "long": {
            "n": 1256,
            "media": 0.04787557858479433,
            "mediana": 0.017830655621516728,
            "hit_rate": 0.5597133757961783
          },
          "short": {
            "n": 1002,
            "media": -0.009588164506211977,
            "mediana": 0.0023991127714494682,
            "hit_rate": 0.5099800399201597
          }
        },
        "28d": {
          "long": {
            "n": 1242,
            "media": 0.08976426339030304,
            "mediana": 0.03239912382069024,
            "hit_rate": 0.5555555555555556
          },
          "short": {
            "n": 1002,
            "media": -0.03764788230637752,
            "mediana": -0.011402333871910617,
            "hit_rate": 0.4740518962075848
          }
        }
      },
      "90": {
        "1d": {
          "long": {
            "n": 1235,
            "media": 0.0028900670132665477,
            "mediana": 0.0012692456266209548,
            "hit_rate": 0.5182186234817814
          },
          "short": {
            "n": 1002,
            "media": -0.001024906465219672,
            "mediana": -0.00036535090132500624,
            "hit_rate": 0.49600798403193613
          }
        },
        "7d": {
          "long": {
            "n": 1229,
            "media": 0.022885139836855483,
            "mediana": 0.007748009573584755,
            "hit_rate": 0.5337672904800651
          },
          "short": {
            "n": 1002,
            "media": -0.004567169393012673,
            "mediana": -0.0018881269579612882,
            "hit_rate": 0.49600798403193613
          }
        },
        "14d": {
          "long": {
            "n": 1222,
            "media": 0.045634328890467965,
            "mediana": 0.018861847488271674,
            "hit_rate": 0.5671031096563012
          },
          "short": {
            "n": 1002,
            "media": -0.01001816127006681,
            "mediana": 0.0077601159846205974,
            "hit_rate": 0.5219560878243513
          }
        },
        "28d": {
          "long": {
            "n": 1208,
            "media": 0.09384875444916373,
            "mediana": 0.04237206920867307,
            "hit_rate": 0.5827814569536424
          },
          "short": {
            "n": 1002,
            "media": -0.024341401712204502,
            "mediana": 0.012887382407795236,
            "hit_rate": 0.5179640718562875
          }
        }
      }
    }
  }
}
```
