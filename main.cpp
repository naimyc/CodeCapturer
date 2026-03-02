#include <thread>
#include <iostream>
#include <mutex>

using namespace std;

mutex mA;
mutex mB;


void task(){
    mA.lock();
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    mB.lock();
    //_..._kritischerAbschnitt...
    mB.unlock();
    mA.unlock();
    
}

void task2(){
    mB.lock();
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    mA.lock();
    //_...kritischerAbschnitt...
    mA.unlock();
    mB.unlock();
    
}