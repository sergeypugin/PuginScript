(program
  (expr (call println "test"))
  (def read_numbers
    (returns int[])
    (block
      (var_decl int count (call input_int))
      (if (<= (identifier count) 0)
        (block
          (return (new int 0))))
      (var_decl int[] numbers (new int (identifier count)))
      (var_decl int i 0)
      (while (< (identifier i) (identifier count))
        (block
          (assign (lv numbers (identifier i)) = (call input_int))
          (assign (lv i) += 1)))
      (return (identifier numbers))))
  (def bubble_sort
    (param int[] a)
    (block
      (var_decl int n (call len (identifier a)))
      (var_decl int i 0)
      (while (< (identifier i) (identifier n))
        (block
          (var_decl int j 0)
          (while (< (identifier j) (- (- (identifier n) 1) (identifier i)))
            (block
              (if (> (index (identifier a) (identifier j)) (index (identifier a) (+ (identifier j) 1)))
                (block
                  (var_decl int temp (index (identifier a) (identifier j)))
                  (assign (lv a (identifier j)) = (index (identifier a) (+ (identifier j) 1)))
                  (assign (lv a (+ (identifier j) 1)) = (identifier temp))))
              (assign (lv j) += 1)))
          (assign (lv i) += 1)))))
  (def print_numbers
    (param int[] a)
    (block
      (var_decl int n (call len (identifier a)))
      (var_decl int i 0)
      (while (< (identifier i) (identifier n))
        (block
          (expr (call println (index (identifier a) (identifier i))))
          (assign (lv i) += 1)))))
  (def main
    (returns int)
    (block
      (var_decl int[] numbers (call read_numbers))
      (expr (call bubble_sort (identifier numbers)))
      (expr (call print_numbers (identifier numbers)))
      (return 0))))
