"""NovaPedidos: interpreta pedidos de WhatsApp para NovaDistribuidora.

Arquitectura (ver DECISIONES.md):

    mensajes ──► llm/ (extracción estructurada) ──► resolucion/ (texto → SKU)
             ──► dominio/ (reglas del negocio, código determinista) ──► api/ (FastAPI)
                                    observabilidad/ (MLflow) envuelve todo el flujo
"""

__version__ = "0.1.0"
