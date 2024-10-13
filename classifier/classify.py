from nudenet import NudeDetector
import cv2
import os
import shutil

allowed_labels = [
    "FEMALE_GENITALIA_COVERED",
    "BUTTOCKS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "MALE_BREAST_EXPOSED",
    "FACE_MALE"
]

def classify_video(video_path, classifier, threshold=0.5, num_frames=100):
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration = total_frames / fps
    classifications = {}
    print(f"Processing video: {os.path.basename(video_path)}")
    # Calculate time interval between frames
    time_interval = duration / num_frames
    for i in range(num_frames):
        # Set position to next time interval
        cap.set(cv2.CAP_PROP_POS_MSEC, i * time_interval * 1000)
        ret, frame = cap.read()
        if not ret:
            break
        # Save frame as temporary image
        temp_image_path = 'temp_frame.jpg'
        cv2.imwrite(temp_image_path, frame)
        # Classify the frame
        result = classifier.detect(temp_image_path)
        # Aggregate classifications
        for detected_object in result:
            label = detected_object['class']
            score = detected_object['score']
            if score > threshold and label in allowed_labels:
                classifications[label] = classifications.get(label, 0) + 1
        # Remove temporary image
        os.remove(temp_image_path)
        # Print progress
        # if (i + 1) % (num_frames // 4) == 0 or i + 1 == num_frames:
        #     progress = ((i + 1) / num_frames) * 100
        #     print(f"Progress: {progress:.0f}%")
    cap.release()
    # Calculate percentages
    for label in classifications:
        classifications[label] = (classifications[label] / num_frames) * 100
    print("Processing complete!")
    return classifications

def matches_rule(classifications, rule):
    for label, threshold in rule['thresholds'].items():
        if label not in classifications or classifications[label] < threshold:
            return False
    return True

def sort_videos_by_rules(video_directory, output_directory, classifier, rules, num_frames=100):
    # Create output directory if it doesn't exist
    os.makedirs(output_directory, exist_ok=True)
    files = os.listdir(video_directory)
    for i, filename in enumerate(files):
        print(f"Processing {i} of {len(files)}")
        if filename.endswith(('.mp4', '.avi', '.mov')):  # Add more video formats if needed
            video_path = os.path.join(video_directory, filename)
            # Classify the video
            try:
                classifications = classify_video(video_path, classifier, num_frames=num_frames)
            except BaseException as e:
                print(f"Unable to process {filename} E:{e}")
            print(classifications)
            # Check if the video matches any rule
            for rule in rules:
                if matches_rule(classifications, rule):
                    # Create rule directory if it doesn't exist
                    rule_dir = os.path.join(output_directory, rule['dir_name'])
                    os.makedirs(rule_dir, exist_ok=True)
                    # Move the video to the rule directory
                    shutil.move(video_path, os.path.join(rule_dir, filename))
                    print(f"Moved {filename} to {rule['dir_name']}")
                    break
            else:
                rule_dir = os.path.join(output_directory, 'unsorted')
                os.makedirs(rule_dir, exist_ok=True)
                shutil.move(video_path, os.path.join(rule_dir, filename))
                print(f"No matching rule for {filename}")

rules = [
    {
        'dir_name': 'couple',
        'thresholds': {
            'MALE_GENITALIA_EXPOSED': 10,
        }
    },
    {
        'dir_name': 'wo_male',
        'thresholds': {
            'FEMALE_GENITALIA_EXPOSED': 20,
        }
    },
    # Add more rules as needed
]

video_directory = ''
output_directory = '/sorted'
def main():
    detector = NudeDetector()
    sort_videos_by_rules(video_directory, output_directory, detector, rules)

if __name__ == '__main__':
    main()
