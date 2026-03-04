#include<stdio.h>
void add(int * z){
    z[2]=3;
}
int main(){
    int i;
    int array1[20];
    int array2[20];
    int array3[20];
    for(i=0;i<20;i++){
        array1[i]=i;
    }
    add(&array1[0]);
    for(i=0;i<20;i++){
        array3[i]=i;
    }
    add(&array3[18]);
    for(i=0;i<20;i++){
        array2[i]=i;
    }
    add(&array2[15]);
    printf("Fertig\n");
    return (0);
}