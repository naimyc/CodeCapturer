CC := gcc

# Enable a broad set of warnings and treat warnings as errors
CFLAGS := -std=c11 -Wall -Wextra -Wpedantic -Wshadow \
          -Wmissing-prototypes -Wstrict-prototypes -Wformat=2 \
          -Wconversion -Wsign-conversion -Wcast-align \
          -Wuninitialized -Winit-self -Wold-style-definition \
          -Wpointer-arith -Wundef -Wredundant-decls 

NAME = main
LDFLAGS :=
SRC := $(NAME).c
OBJ := $(SRC:.c=.o)
TARGET := $(NAME)

.PHONY: all clean run

all: $(TARGET)

$(TARGET): $(OBJ)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	 rm -f $(OBJ) $(TARGET)

run: $(TARGET)
	 ./$(TARGET)
