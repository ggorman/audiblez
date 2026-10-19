---
title: Attention, Briefly
author: "Ada Lovelace"
---

# A Short Paper Summary

Grace Hopper and Alan Turing — arXiv:2601.00001v1, January 2026

5-minute spoken summary | Approximately 300 words | For a general audience

This summary is written to be read aloud.

## Part 1: Background

Transformers map a sequence of tokens to a sequence of vectors. See the [project page](https://example.com/docs) for details.

The attention weight $a_{ij}$ compares token $i$ with token $j$, and **matters** a lot.

$$
a_{ij} = \frac{\exp(q_i \cdot k_j)}{\sum_k \exp(q_i \cdot k_k)}
$$

The model costs $5 to train on a laptop, or $10 with a GPU.

## Part 2: Lists and code

Three ideas matter:

- tight item one
- tight item two
  - nested item

1. Loose item one has a paragraph.

2. Loose item two has a paragraph too.

```python
print("this code should never be read")
```

| Model | Score |
|-------|-------|
| tablecellmarker | 1 |

![a figure](figure.png)

## Conclusion

Use `inline_code` sparingly, and remember that \(x^2\) grows quickly.
