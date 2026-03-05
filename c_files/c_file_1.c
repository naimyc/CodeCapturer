/* ReservierungSpeicherKnotenHeadundKnotenTailaufHeap */
void DefineListenStart(){
    ZeigerHead=(struct knoten *)malloc(sizeof * ZeigerHead);
    ZeigerTail=(struct knoten *)malloc(sizeof * ZeigerTail);
    return;
}
/* FreigabeSpeicherKnotenHeadundKnotenTailaufHeap */
void FreeHeadTail(){
    free(* ZeigerHead);
    return;
}
 /* VerbindeHeadmitTailundTailmitsichselber
: undweiseAnfangswertezu */
void  InitialConnectHeadTail(){
    ZeigerHead->Next=ZeigerTail;
    ZdigerTail->Next=ZeigerTail;
    ZeigerHead->ADCData=-1;
    ZeigerTail->ADCData=-2;
    return;
}