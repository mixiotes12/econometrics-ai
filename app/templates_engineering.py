"""
Datos iniciales editables para las pestañas 2 (Procesos) y 3 (Maquinaria) de cada plantilla.
Los resultados de Presupuestos (Pestaña 4) y Flujograma/Kw/h (Pestaña 2) se dejan en blanco (None)
para que siempre se generen en vivo con IA según los datos actuales del usuario.
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
        "budgets": None,
        "flowchart": None,
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
        "budgets": None,
        "flowchart": None,
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
        "budgets": None,
        "flowchart": None,
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
        "budgets": None,
        "flowchart": None,
    }
}
