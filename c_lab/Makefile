CC := gcc

# Enable a broad set of warnings and treat warnings as errors
CFLAGS := -std=c11 -Wall -Wextra -Wpedantic \
          -Wformat=2 \
          -Wconversion -Wsign-conversion -Wcast-align \
          -Wuninitialized -Winit-self \
          -Wpointer-arith -Wundef \
		  -Wno-unused-parameter -Wno-unused-but-set-variable
NAME = main
LDFLAGS :=
SRC := $(NAME).c
OBJ := $(SRC:.c=.o)
TARGET := $(NAME)

.PHONY: all clean run

all: $(TARGET)

$(TARGET): $(OBJ)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)
	./$(TARGET)
	
	del $(TARGET).o
	del $(TARGET).exe


%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	 del $(TARGET).o
	 del $(TARGET).exe

run: $(TARGET)
	 ./$(TARGET)
