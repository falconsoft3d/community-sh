#!/bin/bash

# Script para aplicar configuración de dominio y SSL
# Este script reinicia los servicios necesarios después de configurar el dominio o SSL

set -e

echo "=================================================="
echo "  Community SH - Aplicar Configuración de Dominio"
echo "=================================================="
echo ""

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Función para imprimir mensajes
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Verificar si Docker está corriendo
if ! docker info > /dev/null 2>&1; then
    print_error "Docker no está corriendo. Por favor, inicia Docker y vuelve a intentar."
    exit 1
fi

# Verificar si docker-compose está disponible
if ! command -v docker-compose &> /dev/null; then
    print_error "docker-compose no está instalado. Por favor, instálalo y vuelve a intentar."
    exit 1
fi

# Menú de opciones
echo "Selecciona la acción a realizar:"
echo ""
echo "1) Aplicar configuración de dominio (HTTP solamente)"
echo "2) Aplicar configuración de dominio con SSL/HTTPS"
echo "3) Solo reiniciar aplicación"
echo "4) Solo reiniciar Traefik"
echo "5) Reiniciar todos los servicios"
echo "6) Ver logs de Traefik"
echo "7) Ver logs de la aplicación"
echo "8) Salir"
echo ""
read -p "Opción: " option

case $option in
    1)
        print_info "Aplicando configuración de dominio (HTTP)..."
        print_warning "Asegúrate de haber configurado el dominio en Settings → Domain & SSL"
        docker-compose up -d --force-recreate app
        print_info "✓ Configuración aplicada. Tu dominio ahora debería funcionar con HTTP."
        ;;
    2)
        print_info "Aplicando configuración de dominio con SSL/HTTPS..."
        print_warning "Asegúrate de:"
        print_warning "  1. Haber configurado el dominio en Settings → Domain & SSL"
        print_warning "  2. Haber generado el certificado SSL con Let's Encrypt"
        print_warning "  3. Tu dominio apunta a la IP de este servidor"
        print_warning "  4. Los puertos 80 y 443 están abiertos"
        echo ""
        read -p "¿Continuar? (s/n): " confirm
        if [[ $confirm == "s" || $confirm == "S" ]]; then
            docker-compose up -d --force-recreate app traefik
            print_info "✓ Configuración HTTPS aplicada. Tu dominio ahora debería funcionar con HTTPS."
            print_info "Verifica accediendo a: https://tudominio.com"
        else
            print_info "Operación cancelada."
        fi
        ;;
    3)
        print_info "Reiniciando aplicación..."
        docker-compose restart app
        print_info "✓ Aplicación reiniciada."
        ;;
    4)
        print_info "Reiniciando Traefik..."
        docker-compose restart traefik
        print_info "✓ Traefik reiniciado."
        ;;
    5)
        print_info "Reiniciando todos los servicios..."
        docker-compose restart
        print_info "✓ Todos los servicios reiniciados."
        ;;
    6)
        print_info "Mostrando logs de Traefik (Ctrl+C para salir)..."
        docker-compose logs -f traefik
        ;;
    7)
        print_info "Mostrando logs de la aplicación (Ctrl+C para salir)..."
        docker-compose logs -f app
        ;;
    8)
        print_info "Saliendo..."
        exit 0
        ;;
    *)
        print_error "Opción inválida."
        exit 1
        ;;
esac

echo ""
echo "=================================================="
echo ""
print_info "Comandos útiles:"
echo "  - Ver logs:        docker-compose logs -f [servicio]"
echo "  - Reiniciar:       docker-compose restart [servicio]"
echo "  - Estado:          docker-compose ps"
echo ""
print_info "Para verificar que tu dominio funciona:"
echo "  - HTTP:  curl http://tudominio.com"
echo "  - HTTPS: curl https://tudominio.com"
echo ""
print_info "Dashboard de Traefik: http://localhost:8080"
echo ""
