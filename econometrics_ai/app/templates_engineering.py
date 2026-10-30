"""
Datos de ejemplo para las pestañas 1 (Presupuestos) y 2 (Procesos) de cada plantilla.

Cada entrada incluye:
- equipment_items: renglones del formulario de presupuestos (categoría, nombre, especificación).
- process_description: texto del proceso productivo.
- budgets: 3 presupuestos precalculados (Económico / Estándar / Premium). El Estándar
  coincide con la inversión inicial de la plantilla.
- flowchart: diagrama Mermaid, actividades y tabla de consumibles precalculados.

Los resultados precalculados permiten ver la plantilla completa sin consumir la API;
el usuario puede regenerarlos con Gemini en cualquier momento.
"""

ENGINEERING_TEMPLATES = {
    "cafe_especialidad": {
        "equipment_items": [
            {"category": "Maquinaria", "name": "Máquina Espresso", "description": "2 grupos, caldera 10 L, semiautomática, nueva"},
            {"category": "Maquinaria", "name": "Molino de café", "description": "Muelas planas 64 mm, dosificación por tiempo"},
            {"category": "Maquinaria", "name": "Tostador de café", "description": "Capacidad 1 kg/lote, a gas LP, con enfriador"},
            {"category": "Maquinaria", "name": "Vitrina refrigerada y horno", "description": "Vitrina 1.2 m + horno de convección 4 charolas"},
            {"category": "Servicios", "name": "Adecuación y licencias", "description": "Instalación eléctrica/hidráulica, licencia de funcionamiento, Protección Civil"},
            {"category": "Empleados", "name": "Baristas", "description": "Reclutamiento y capacitación de 3 baristas (1 mes)"}
        ],
        "process_description": (
            "1. Recepción e inspección de grano verde en almacén. "
            "2. Tueste por lotes de 1 kg (12-15 min a 200-220 °C) y enfriamiento. "
            "3. Reposo del grano tostado 24-48 h en contenedores herméticos. "
            "4. Molienda al momento según método de extracción. "
            "5. Extracción de espresso / métodos (25-30 s por shot) y preparación de bebidas. "
            "6. Entrega al cliente en barra o mesa y cobro en TPV. "
            "7. Limpieza de grupos, molino y área de trabajo al cierre."
        ),
        "budgets": {
            "budgets": [
                {"budget_type": "Económico", "total_cost": 245000.0, "details": [
                    "Máquina espresso 2 grupos (marca nacional/italiana de entrada) - $85,000 MXN",
                    "Molino muelas planas 64 mm - $18,000 MXN",
                    "Tostador 1 kg fabricación nacional - $65,000 MXN",
                    "Vitrina refrigerada + horno convección básico - $32,000 MXN",
                    "Adecuación y licencias - $30,000 MXN",
                    "Reclutamiento y capacitación baristas - $15,000 MXN"
                ]},
                {"budget_type": "Estándar", "total_cost": 350000.0, "details": [
                    "Máquina espresso 2 grupos multicaldera - $130,000 MXN",
                    "Molino on-demand 64 mm con temporizador - $28,000 MXN",
                    "Tostador 1 kg con enfriador y software de perfiles - $95,000 MXN",
                    "Vitrina refrigerada 1.2 m + horno 4 charolas - $42,000 MXN",
                    "Adecuación y licencias - $35,000 MXN",
                    "Reclutamiento y capacitación baristas - $20,000 MXN"
                ]},
                {"budget_type": "Premium", "total_cost": 520000.0, "details": [
                    "Máquina espresso 2 grupos con perfilado de presión - $210,000 MXN",
                    "Molino premium 75 mm con dosificación gravimétrica - $45,000 MXN",
                    "Tostador 1.5 kg importado con monitoreo de curva - $150,000 MXN",
                    "Vitrina de diseño + horno combinado - $55,000 MXN",
                    "Adecuación, diseño interior y licencias - $40,000 MXN",
                    "Capacitación certificada SCA para baristas - $20,000 MXN"
                ]}
            ],
            "summary": "Se recomienda la opción Estándar: equilibra durabilidad y costo, y el tostador con software permite estandarizar la calidad 86+ SCA, que es la ventaja competitiva del negocio. La opción Económica eleva el riesgo de mantenimiento; la Premium solo se justifica con volumen superior a 4,000 bebidas/mes.",
            "generated_at": "Plantilla de ejemplo"
        },
        "flowchart": {
            "mermaid_code": (
                "flowchart LR\n"
                "  A([Inicio]) --> B[(Almacén de grano verde)]\n"
                "  B --> C[Tueste por lote]\n"
                "  C --> D{¿Curva de tueste correcta?}\n"
                "  D -->|No| C\n"
                "  D -->|Sí| E[(Reposo 24-48 h)]\n"
                "  E --> F[Molienda al momento]\n"
                "  F --> G[Extracción y preparación]\n"
                "  G --> H[Entrega y cobro]\n"
                "  H --> I[Limpieza de equipo]\n"
                "  I --> J([Fin])"
            ),
            "activities": [
                {"step_number": 1, "activity": "Recepción e inspección de grano verde", "time_estimate": "15 min/lote", "movements": "Descarga de costales al almacén seco"},
                {"step_number": 2, "activity": "Tueste y enfriamiento", "time_estimate": "15 min/kg", "movements": "Almacén → tostador → bandeja de enfriamiento"},
                {"step_number": 3, "activity": "Reposo del grano tostado", "time_estimate": "24-48 h", "movements": "Traslado a contenedores herméticos"},
                {"step_number": 4, "activity": "Molienda", "time_estimate": "10 s/porción", "movements": "Tolva → portafiltro"},
                {"step_number": 5, "activity": "Extracción y preparación de bebida", "time_estimate": "2-3 min/bebida", "movements": "Barra de trabajo (movimientos cortos)"},
                {"step_number": 6, "activity": "Entrega y cobro", "time_estimate": "1 min", "movements": "Barra → cliente → TPV"},
                {"step_number": 7, "activity": "Limpieza de cierre", "time_estimate": "40 min/día", "movements": "Recorrido por barra, molino y tostador"}
            ],
            "consumables_table": [
                {"item_name": "Energía eléctrica (espresso, molino, refrigeración, horno)", "quantity_monthly": "1,350 Kw/h", "monthly_cost_estimate": 4050.0},
                {"item_name": "Gas LP (tostador)", "quantity_monthly": "120 L", "monthly_cost_estimate": 1500.0},
                {"item_name": "Agua filtrada", "quantity_monthly": "18 m3", "monthly_cost_estimate": 900.0},
                {"item_name": "Vasos, tapas y filtros desechables", "quantity_monthly": "1,200 pzas", "monthly_cost_estimate": 3200.0}
            ],
            "total_monthly_consumables_cost": 9650.0,
            "generated_at": "Plantilla de ejemplo"
        }
    },

    "ecommerce_d2c": {
        "equipment_items": [
            {"category": "Maquinaria", "name": "Mezcladora-emulsificadora", "description": "Acero inoxidable 316, 50 L, con calentamiento"},
            {"category": "Maquinaria", "name": "Llenadora semiautomática", "description": "Pistón, 10-250 ml, para cremas y sueros"},
            {"category": "Maquinaria", "name": "Etiquetadora", "description": "Semiautomática para envases redondos"},
            {"category": "Servicios", "name": "Tienda en línea y fotografía", "description": "Shopify, integración Amazon/MercadoLibre, sesión de producto"},
            {"category": "Servicios", "name": "Trámites sanitarios", "description": "Aviso de funcionamiento COFEPRIS y registro de marca IMPI"},
            {"category": "Empleados", "name": "Químico formulador", "description": "Contratación y primer mes de nómina"}
        ],
        "process_description": (
            "1. Recepción de insumos (activos botánicos, bases, envases). "
            "2. Pesaje de materias primas según fórmula. "
            "3. Mezcla y emulsión a 70 °C por 30 min. "
            "4. Control de calidad (pH, viscosidad, apariencia). "
            "5. Llenado de envases y sellado. "
            "6. Etiquetado y loteado. "
            "7. Envío del inventario al almacén 3PL y despacho de pedidos."
        ),
        "budgets": {
            "budgets": [
                {"budget_type": "Económico", "total_cost": 140000.0, "details": [
                    "Mezcladora 30 L nacional - $38,000 MXN",
                    "Llenadora manual de pistón - $14,000 MXN",
                    "Etiquetadora manual - $6,000 MXN",
                    "Tienda Shopify plantilla + fotografía básica - $22,000 MXN",
                    "Trámites COFEPRIS e IMPI - $15,000 MXN",
                    "Formulador (primer mes) + inventario inicial de envases - $45,000 MXN"
                ]},
                {"budget_type": "Estándar", "total_cost": 200000.0, "details": [
                    "Mezcladora-emulsificadora 50 L acero 316 - $62,000 MXN",
                    "Llenadora semiautomática de pistón - $26,000 MXN",
                    "Etiquetadora semiautomática - $14,000 MXN",
                    "Tienda Shopify + integraciones + fotografía - $30,000 MXN",
                    "Trámites COFEPRIS e IMPI - $18,000 MXN",
                    "Formulador (primer mes) + inventario inicial - $50,000 MXN"
                ]},
                {"budget_type": "Premium", "total_cost": 310000.0, "details": [
                    "Mezcladora al vacío 50 L con homogeneizador - $115,000 MXN",
                    "Llenadora neumática con dosificación digital - $45,000 MXN",
                    "Etiquetadora automática - $32,000 MXN",
                    "Tienda personalizada + contenido audiovisual - $45,000 MXN",
                    "Trámites COFEPRIS, IMPI y pruebas de estabilidad - $23,000 MXN",
                    "Formulador senior + inventario inicial - $50,000 MXN"
                ]}
            ],
            "summary": "La opción Estándar cubre la capacidad para ~850 pedidos/mes con margen de crecimiento. La Premium reduce mermas por aire en la emulsión, conveniente cuando las ventas superen 2,000 unidades/mes.",
            "generated_at": "Plantilla de ejemplo"
        },
        "flowchart": {
            "mermaid_code": (
                "flowchart LR\n"
                "  A([Inicio]) --> B[(Insumos y envases)]\n"
                "  B --> C[Pesaje por fórmula]\n"
                "  C --> D[Mezcla y emulsión 70 °C]\n"
                "  D --> E{¿pH y viscosidad OK?}\n"
                "  E -->|No| D\n"
                "  E -->|Sí| F[Llenado y sellado]\n"
                "  F --> G[Etiquetado y loteado]\n"
                "  G --> H[(Almacén 3PL)]\n"
                "  H --> I[Despacho de pedidos]\n"
                "  I --> J([Fin])"
            ),
            "activities": [
                {"step_number": 1, "activity": "Recepción de insumos", "time_estimate": "30 min", "movements": "Andén → almacén de materia prima"},
                {"step_number": 2, "activity": "Pesaje por fórmula", "time_estimate": "20 min/lote", "movements": "Almacén → báscula"},
                {"step_number": 3, "activity": "Mezcla y emulsión", "time_estimate": "45 min/lote", "movements": "Báscula → mezcladora"},
                {"step_number": 4, "activity": "Control de calidad", "time_estimate": "15 min/lote", "movements": "Toma de muestra en mezcladora"},
                {"step_number": 5, "activity": "Llenado y sellado", "time_estimate": "8 s/pieza", "movements": "Mezcladora → llenadora"},
                {"step_number": 6, "activity": "Etiquetado y loteado", "time_estimate": "5 s/pieza", "movements": "Llenadora → etiquetadora → cajas"},
                {"step_number": 7, "activity": "Envío a 3PL y despacho", "time_estimate": "1 h/semana", "movements": "Carga a paquetería"}
            ],
            "consumables_table": [
                {"item_name": "Energía eléctrica (mezcladora, llenadora)", "quantity_monthly": "380 Kw/h", "monthly_cost_estimate": 1140.0},
                {"item_name": "Agua desmineralizada", "quantity_monthly": "2 m3", "monthly_cost_estimate": 1200.0},
                {"item_name": "Empaques biodegradables", "quantity_monthly": "900 pzas", "monthly_cost_estimate": 6500.0},
                {"item_name": "Material de envío (cajas, relleno)", "quantity_monthly": "850 pzas", "monthly_cost_estimate": 4200.0}
            ],
            "total_monthly_consumables_cost": 13040.0,
            "generated_at": "Plantilla de ejemplo"
        }
    },

    "saas_b2b": {
        "equipment_items": [
            {"category": "Maquinaria", "name": "Laptops de desarrollo", "description": "4 equipos, 16-32 GB RAM, SSD 1 TB, nuevos"},
            {"category": "Maquinaria", "name": "Equipo de red y oficina", "description": "Router empresarial, monitores 27\", sillas ergonómicas"},
            {"category": "Servicios", "name": "Infraestructura en la nube", "description": "AWS (cómputo, base de datos, respaldos) primeros 3 meses"},
            {"category": "Servicios", "name": "Licencias y legal", "description": "Constitución, aviso de privacidad, WhatsApp Business API"},
            {"category": "Empleados", "name": "Desarrolladores y UX", "description": "Reclutamiento de 2 desarrolladores y 1 diseñador UX"}
        ],
        "process_description": (
            "1. Captación de prospectos por campañas digitales. "
            "2. Demo en línea con el médico o clínica (30 min). "
            "3. Decisión de compra y alta en la plataforma. "
            "4. Onboarding y configuración de agenda y expediente (10 min). "
            "5. Uso diario y recordatorios automáticos por WhatsApp. "
            "6. Soporte humano 24/7 ante incidencias. "
            "7. Renovación mensual de la suscripción."
        ),
        "budgets": {
            "budgets": [
                {"budget_type": "Económico", "total_cost": 195000.0, "details": [
                    "4 laptops gama media - $72,000 MXN",
                    "Red y mobiliario básico - $18,000 MXN",
                    "AWS 3 meses (instancias pequeñas) - $25,000 MXN",
                    "Licencias y legal - $20,000 MXN",
                    "Reclutamiento de equipo - $60,000 MXN"
                ]},
                {"budget_type": "Estándar", "total_cost": 280000.0, "details": [
                    "4 laptops profesionales 32 GB - $110,000 MXN",
                    "Red empresarial, monitores y sillas - $30,000 MXN",
                    "AWS 3 meses con base de datos administrada - $35,000 MXN",
                    "Licencias, legal y WhatsApp API - $25,000 MXN",
                    "Reclutamiento de equipo - $80,000 MXN"
                ]},
                {"budget_type": "Premium", "total_cost": 410000.0, "details": [
                    "4 laptops alto desempeño + equipo de pruebas - $165,000 MXN",
                    "Oficina equipada y videoconferencia - $55,000 MXN",
                    "AWS multi-zona con alta disponibilidad - $60,000 MXN",
                    "Licencias, legal y certificación de seguridad - $40,000 MXN",
                    "Reclutamiento con headhunter - $90,000 MXN"
                ]}
            ],
            "summary": "La opción Estándar ofrece la infraestructura administrada necesaria para cumplir con la protección de datos de salud sin sobreinvertir antes de validar 180 clientes.",
            "generated_at": "Plantilla de ejemplo"
        },
        "flowchart": {
            "mermaid_code": (
                "flowchart LR\n"
                "  A([Prospecto]) --> B[Campaña digital]\n"
                "  B --> C[Demo en línea]\n"
                "  C --> D{¿Contrata?}\n"
                "  D -->|No| B\n"
                "  D -->|Sí| E[Alta y onboarding]\n"
                "  E --> F[(Base de datos de pacientes)]\n"
                "  F --> G[Uso diario y recordatorios]\n"
                "  G --> H{¿Incidencia?}\n"
                "  H -->|Sí| I[Soporte 24/7]\n"
                "  I --> G\n"
                "  H -->|No| J([Renovación mensual])"
            ),
            "activities": [
                {"step_number": 1, "activity": "Captación de prospectos", "time_estimate": "Continuo", "movements": "Ninguno (digital)"},
                {"step_number": 2, "activity": "Demo en línea", "time_estimate": "30 min", "movements": "Videollamada"},
                {"step_number": 3, "activity": "Alta en la plataforma", "time_estimate": "5 min", "movements": "Ninguno (digital)"},
                {"step_number": 4, "activity": "Onboarding y configuración", "time_estimate": "10 min", "movements": "Ninguno (digital)"},
                {"step_number": 5, "activity": "Uso diario y recordatorios", "time_estimate": "Automático", "movements": "Ninguno (digital)"},
                {"step_number": 6, "activity": "Soporte a incidencias", "time_estimate": "15 min/ticket", "movements": "Chat / llamada"},
                {"step_number": 7, "activity": "Renovación de suscripción", "time_estimate": "Automático", "movements": "Cobro recurrente"}
            ],
            "consumables_table": [
                {"item_name": "Energía eléctrica oficina", "quantity_monthly": "420 Kw/h", "monthly_cost_estimate": 1260.0},
                {"item_name": "Cómputo en la nube (AWS)", "quantity_monthly": "Instancias + BD", "monthly_cost_estimate": 9500.0},
                {"item_name": "Mensajes WhatsApp Business API", "quantity_monthly": "12,000 mensajes", "monthly_cost_estimate": 3800.0},
                {"item_name": "Internet fibra empresarial", "quantity_monthly": "1 servicio", "monthly_cost_estimate": 900.0}
            ],
            "total_monthly_consumables_cost": 15460.0,
            "generated_at": "Plantilla de ejemplo"
        }
    },

    "gimnasio_boutique": {
        "equipment_items": [
            {"category": "Maquinaria", "name": "Pilates Reformer", "description": "8 unidades, estructura de aluminio, resortes intercambiables"},
            {"category": "Maquinaria", "name": "Equipo HIIT", "description": "4 remadoras de aire, 4 bicicletas de asalto, mancuernas y kettlebells"},
            {"category": "Maquinaria", "name": "Climatización y audio", "description": "Minisplits 3 TR x2, sistema de audio y micrófono inalámbrico"},
            {"category": "Servicios", "name": "Adecuación del local", "description": "Piso de caucho, regaderas, vestidores, licencia de funcionamiento"},
            {"category": "Empleados", "name": "Coaches certificados", "description": "Reclutamiento y certificación de 4 coaches"}
        ],
        "process_description": (
            "1. Reserva de clase por app con créditos. "
            "2. Check-in del cliente en recepción. "
            "3. Calentamiento guiado (10 min). "
            "4. Clase de Reformer o HIIT (40 min) con máximo 12 personas. "
            "5. Estiramiento y cierre (5 min). "
            "6. Renovación de créditos o membresía. "
            "7. Limpieza y desinfección de equipo entre clases."
        ),
        "budgets": {
            "budgets": [
                {"budget_type": "Económico", "total_cost": 470000.0, "details": [
                    "8 Reformers fabricación nacional - $200,000 MXN",
                    "Equipo HIIT básico - $90,000 MXN",
                    "Climatización y audio - $55,000 MXN",
                    "Adecuación del local y licencias - $95,000 MXN",
                    "Reclutamiento de coaches - $30,000 MXN"
                ]},
                {"budget_type": "Estándar", "total_cost": 650000.0, "details": [
                    "8 Reformers de aluminio importados - $320,000 MXN",
                    "Equipo HIIT comercial - $120,000 MXN",
                    "Climatización y audio profesional - $65,000 MXN",
                    "Adecuación del local y licencias - $110,000 MXN",
                    "Reclutamiento y certificación de coaches - $35,000 MXN"
                ]},
                {"budget_type": "Premium", "total_cost": 920000.0, "details": [
                    "8 Reformers marca líder con torre - $480,000 MXN",
                    "Equipo HIIT de gama alta con monitoreo - $170,000 MXN",
                    "Climatización inverter, audio e iluminación - $90,000 MXN",
                    "Adecuación de diseño y licencias - $140,000 MXN",
                    "Certificación internacional de coaches - $40,000 MXN"
                ]}
            ],
            "summary": "La opción Estándar garantiza equipo durable para 6-8 clases diarias. La Económica implica mayor desgaste de resortes y reposición anticipada; la Premium refuerza la imagen exclusiva pero alarga el periodo de recuperación.",
            "generated_at": "Plantilla de ejemplo"
        },
        "flowchart": {
            "mermaid_code": (
                "flowchart LR\n"
                "  A([Reserva en app]) --> B[Check-in en recepción]\n"
                "  B --> C[Calentamiento guiado]\n"
                "  C --> D[Clase Reformer o HIIT]\n"
                "  D --> E[Estiramiento y cierre]\n"
                "  E --> F{¿Le quedan créditos?}\n"
                "  F -->|No| G[Renovación de membresía]\n"
                "  F -->|Sí| H[Limpieza de equipo]\n"
                "  G --> H\n"
                "  H --> I([Siguiente clase])"
            ),
            "activities": [
                {"step_number": 1, "activity": "Reserva de clase", "time_estimate": "1 min", "movements": "Ninguno (app)"},
                {"step_number": 2, "activity": "Check-in", "time_estimate": "1 min", "movements": "Entrada → recepción → vestidores"},
                {"step_number": 3, "activity": "Calentamiento", "time_estimate": "10 min", "movements": "Vestidores → sala"},
                {"step_number": 4, "activity": "Clase Reformer / HIIT", "time_estimate": "40 min", "movements": "Rotación entre estaciones"},
                {"step_number": 5, "activity": "Estiramiento y cierre", "time_estimate": "5 min", "movements": "En sala"},
                {"step_number": 6, "activity": "Renovación de créditos", "time_estimate": "2 min", "movements": "Sala → recepción"},
                {"step_number": 7, "activity": "Limpieza y desinfección", "time_estimate": "10 min", "movements": "Recorrido por cada equipo"}
            ],
            "consumables_table": [
                {"item_name": "Energía eléctrica (climatización, audio, iluminación)", "quantity_monthly": "1,600 Kw/h", "monthly_cost_estimate": 4800.0},
                {"item_name": "Agua (regaderas, limpieza)", "quantity_monthly": "35 m3", "monthly_cost_estimate": 1750.0},
                {"item_name": "Gas LP (calentador)", "quantity_monthly": "110 L", "monthly_cost_estimate": 1400.0},
                {"item_name": "Toallas, desinfectante y artículos de limpieza", "quantity_monthly": "Lote mensual", "monthly_cost_estimate": 2600.0}
            ],
            "total_monthly_consumables_cost": 10550.0,
            "generated_at": "Plantilla de ejemplo"
        }
    }
}
