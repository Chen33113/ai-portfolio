# AI辅助编程实录 - W3 生词表CSV自动生成练习题

## 1. 任务与提示词
**要做什么：** 读取生词表CSV，按HSK4筛选，统计词性分布，并生成造句练习题到txt文件。
**我写的提示词（四件套）：**
> 角色：你是Python教学助手。
> 任务：写脚本读生词表CSV并生成练习题。
> 要求：按HSK等级筛选、统计词性分布、输出txt，仅用标准库，每行加注释。
> 示例：期望输出 用“坚持”造一个句子。（动词）

## 2. AI 初版代码
import csv

# 1. 读取生词表
def read_vocab(filepath):
    words = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            words.append(row)
    return words

# 2. 按HSK等级筛选
def filter_by_level(words, level):
    result = []
    for w in words:
        if w['HSK等级'] == level:
            result.append(w)
    return result

# 3. 统计词性分布
def count_pos(words):
    pos_dict = {}
    for w in words:
        pos = w['词性']
        if pos in pos_dict:
            pos_dict[pos] += 1
        else:
            pos_dict[pos] = 1
    return pos_dict

# 4. 生成练习题并写入txt
def generate_exercises(words, output_file):
    with open(output_file, 'w') as f:
        for w in words:
            # 按照要求的格式生成句子
            sentence = f"用“{w['词汇']}”造一个句子。（{w['词性']}）\n"
            f.write(sentence)

# 主程序运行
if __name__ == "__main__":
    # 读取数据
    all_words = read_vocab("data/生词表.csv")
    
    # 筛选 HSK4 词汇
    hsk4_words = filter_by_level(all_words, "4")
    
    # 打印统计信息
    total = len(all_words)
    hsk4_total = len(hsk4_words)
    pos_dist = count_pos(hsk4_words)
    print(f"总词汇 {total} 个，其中 HSK4 词汇 {hsk4_total} 个，词性分布：{pos_dist}")
    
    # 生成文件
    generate_exercises(hsk4_words, "练习.txt")
    print("已生成: 练习.txt")

## 3. 我的修改点（≥3条，必须写清“为什么”）
1. **添加了文件编码设置**:
改了什么：AI 初版在读取和写入文件时写的是 open(filepath, 'r')，我修改为 open(filepath, 'r', encoding="utf-8") 和 open(out, "w", encoding="utf-8")。
为什么改：因为生词表里包含中文字符。如果不指定 UTF-8 编码，在 Windows 系统下运行程序会出现中文乱码，导致输出的练习题无法正常阅读。这是处理中文字符时的必备操作。
2. **统一了文件路径管理**：改了什么：AI 初版直接写死了相对路径 "data/生词表.csv" 和 "练习.txt"。我使用了 weekpath.data_path() 和 weekpath.root_path() 来动态解析路径。
为什么改：直接写相对路径会导致一个致命问题——“从哪里运行命令，文件就生成在哪里”。如果我在别的目录下运行脚本，就会找不到输入文件，且生成的 练习.txt 会散落在各个文件夹里。统一到代码包根目录，符合工程规范，避免污染工作区。
3. **增加了数据类型强制转换**：改了什么：AI 初版判断 HSK 等级时写的是 if w['HSK等级'] == level。我修改为了 if str(w["HSK等级"]) == str(level)。
为什么改：从 CSV 读取出来的数据默认是字符串（如 '4'），而我们在调用函数时可能会习惯性地传入整数 4。强制转换为字符串再比较，可以避免因数据类型不一致导致筛选失败（一条数据都筛不出来）。

## 4. 最终版 vs 初版差异说明
*   **AI 想多了的地方**：AI 在生成初版代码时，严格按照了“仅用标准库”的要求，没有胡乱引入第三方库，这一点是好的。但是在数据筛选上，AI 依然使用了偏向底层的 for 循环，显得有些繁琐。
*   **AI 漏掉的地方**：AI 严重缺乏处理真实文件的“工程经验”。它漏掉了中文字符的编码声明（会导致乱码），漏掉了跨目录运行的路径处理（会导致找不到文件和产物乱跑），也漏掉了对数据类型（字符串与数字）的防御性判断。
*   **我为什么这么改**：1.加上 encoding="utf-8"，是为了解决 Windows 系统下读写中文 CSV 和 TXT 必定会出现的乱码问题。
2.引入 weekpath 封装路径，是为了履行幻灯片强调的“任意目录运行”承诺，防止生成的练习文件污染代码工作区。
3.加上 str() 强制转换，是为了避免因为 CSV 读出来是字符串而外部传入数字导致的 KeyError 筛选失败。