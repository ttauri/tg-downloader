for k, v in l.items():
    print(f"Group name: {k}")
    print(f"Number of videos for concatenation: {len(v)}")
    groups = merge_small_groups_of_lists(group_by_bitrate(v))
    print(f"Length of concatenanted video (Min) \n {[int(sum([g[1] for g in group])/60) for group in groups]}")
    print(f"Bitrate diffenence in group \n {[int(max([y[0] for y in x]) - min(y[0] for y in x)) for x in groups]}")
    print(" *"* 10)


def group_by_length(elems):
    # Define the groups
    groups = {
        "shorter_than_60_sec": [],
        "60_to_250_sec": [],
        "250_to_750_sec": [],
        "750_and_above_sec": [],
    }
    # Iterate through each element
    for bitrate, length in elems:
        if length < 60:
            groups["shorter_than_60_sec"].append((bitrate, length))
        elif 60 <= length < 250:
            groups["60_to_250_sec"].append((bitrate, length))
        elif 250 <= length < 750:
            groups["250_to_750_sec"].append((bitrate, length))
        else:
            groups["750_and_above_sec"].append((bitrate, length))
    return groups


def percentile(data, p):
    """Calculate the p-th percentile of a list of numbers."""
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_data):
        return sorted_data[f] * (1 - c) + sorted_data[f + 1] * c
    return sorted_data[f]


def group_by_bitrate(elems):
    grouped = []
    group = []
    first = None
    for elem in elems:
        if not first:
            first = elem
        if elem['bit_rate'] / first['bit_rate'] > 1.1:
            if group:  # Only append non-empty groups
                grouped.append(group)
            group = [elem]
            first = elem
        else:
            group.append(elem)
    # Append the last group if it's not empty
    if group:
        grouped.append(group)
    return grouped


def merge_small_groups_of_lists(groups):
    def calculate_target_size(groups):
        avg_group_len = int(percentile([len(g) for g in groups], 0.9))
        print("avg_group_len", avg_group_len)
        return avg_group_len

    def split_large_group(group, target_size):
        return [group[i:i + target_size] for i in range(0, len(group), target_size)]

    target_size = calculate_target_size(groups)
    merged_groups = []
    current_group = []

    for group in groups:
        if len(current_group) + len(group) <= target_size * 1.5:  # Allow some flexibility
            current_group.extend(group)
        else:
            if current_group:
                if len(current_group) > target_size * 1.5:
                    merged_groups.extend(split_large_group(current_group, target_size))
                else:
                    merged_groups.append(current_group)
            current_group = group

    if current_group:
        if len(current_group) > target_size * 1.5:
            merged_groups.extend(split_large_group(current_group, target_size))
        else:
            merged_groups.append(current_group)

    # Final pass to merge any remaining small groups
    final_groups = []
    for group in merged_groups:
        if final_groups and len(final_groups[-1]) < target_size * 0.5:
            final_groups[-1].extend(group)
        else:
            final_groups.append(group)

    return final_groups