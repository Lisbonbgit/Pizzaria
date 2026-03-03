#!/usr/bin/env python3
"""
Script para gerar hash da senha do administrador.

Uso:
    python generate_password_hash.py

O script irá pedir a senha e retornar o hash bcrypt para colocar no .env
"""

import bcrypt
import getpass

def generate_hash():
    print("=" * 50)
    print("GERADOR DE HASH DE SENHA - ADMIN")
    print("=" * 50)
    print()
    
    # Pedir a senha
    password = getpass.getpass("Digite a nova senha do admin: ")
    
    if len(password) < 6:
        print("\nERRO: A senha deve ter pelo menos 6 caracteres!")
        return
    
    # Confirmar a senha
    password_confirm = getpass.getpass("Confirme a senha: ")
    
    if password != password_confirm:
        print("\nERRO: As senhas não coincidem!")
        return
    
    # Gerar o hash
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    print()
    print("=" * 50)
    print("HASH GERADO COM SUCESSO!")
    print("=" * 50)
    print()
    print("Copie a linha abaixo para o ficheiro .env do backend:")
    print()
    print(f'ADMIN_PASSWORD_HASH="{password_hash}"')
    print()
    print("=" * 50)
    print()
    print("Após alterar o .env, reinicie o backend:")
    print("  sudo supervisorctl restart backend")
    print()

if __name__ == "__main__":
    generate_hash()
