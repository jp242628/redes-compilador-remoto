#include <stdio.h>

int main() {
    int a = 12; // 1100 em binário
    int b = 10; // 1010 em binário
    
    // Operação XOR
    int resultado = a ^ b; 
    
    printf("O resultado da operacao XOR e: %d\n", resultado);
    return 0;
}