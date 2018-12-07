#!/usr/bin/env python
# -*- coding: utf-8 -*-
# author: Yizhong
# created_at: 16-12-6 下午2:54

import os
import argparse
import tensorflow as tf
from lstm import QaLSTM
from data_helper import DataHelper
from data_helper import get_final_rank
from eval import eval_map_mrr

embedding_file = '../Question-Retrieval/glove.6B.300d.txt'
train_file = 'data/lemmatized/WikiQA-train.tsv'
dev_file = 'data/lemmatized/WikiQA-dev.tsv'
test_file = 'data/lemmatized/WikiQA-test.tsv'
train_triplets_file = 'data/lemmatized/WikiQA-train-triplets.tsv'


def prepare_helper():
    data_helper = DataHelper()
    data_helper.build(embedding_file, train_file, dev_file, test_file)
    data_helper.save('data/model/data_helper_info.bin')


def train_lstm():
    data_helper = DataHelper()
    data_helper.restore('data/model/data_helper_info.bin')
    data_helper.prepare_train_triplets('data/lemmatized/WikiQA-train-triplets.tsv')
    data_helper.prepare_dev_data('data/lemmatized/WikiQA-dev.tsv')
    data_helper.prepare_test_data('data/lemmatized/WikiQA-test.tsv')
    lstm_model = QaLSTM(
        q_length=data_helper.max_q_length,
        a_length=data_helper.max_a_length,
        word_embeddings=data_helper.embeddings,
        LSTM_hidden_size = 300,
        margin=0.25,
        l2_reg_lambda=0
    )

    global_step = tf.Variable(0, name='global_step', trainable=False)

    optimizer = tf.train.AdamOptimizer(learning_rate=1e-3)
    train_op = optimizer.minimize(lstm_model.loss, global_step=global_step)

    checkpoint_dir = os.path.abspath('data/model/checkpoints')
    checkpoint_model_path = os.path.join(checkpoint_dir, 'model.ckpt')
    if not os.path.exists(checkpoint_dir):
        os.mkdir(checkpoint_dir)
    saver = tf.train.Saver()

    with tf.Session() as sess:
        summary_writer = tf.summary.FileWriter ('data/model/summary', sess.graph)
        sess.run(tf.global_variables_initializer())
        for epoch in range(10):
            train_loss = 0
            for batch in data_helper.gen_train_batches(batch_size=15):
                q_batch, pos_a_batch, neg_a_batch, q_length_batch, pa_length_batch, na_length_batch = zip(*batch)
                _, loss, summaries = sess.run([train_op, lstm_model.loss, lstm_model.summary_op],
                                              feed_dict={lstm_model.question: q_batch,
                                                         lstm_model.pos_answer: pos_a_batch,
                                                         lstm_model.neg_answer: neg_a_batch,
                                                         lstm_model.question_length : q_length_batch,
                                                         lstm_model.pos_answer_length : pa_length_batch,
                                                         lstm_model.neg_answer_length : na_length_batch
                                              })
                train_loss += loss
                cur_step = tf.train.global_step(sess, global_step)
                summary_writer.add_summary(summaries, cur_step)
                if cur_step % 10 == 0:
                    # print('Loss: {}'.format(train_loss))
                    # test on dev set
                    q_dev, ans_dev, q_length, ans_length = zip(*data_helper.dev_data)
                    similarity_scores = sess.run(lstm_model.pos_similarity, feed_dict={lstm_model.question: q_dev,
                                                                                       lstm_model.pos_answer: ans_dev,
                                                                                       lstm_model.question_length: q_length,
                                                                                       lstm_model.pos_answer_length: ans_length,
                })
                    for sample, similarity_score in zip(data_helper.dev_samples, similarity_scores):
                        sample.score = similarity_score
                    with open('data/output/WikiQA-dev.rank'.format(epoch), 'w') as fout:
                        for sample, rank in get_final_rank(data_helper.dev_samples):
                            fout.write('{}\t{}\t{}\n'.format(sample.q_id, sample.a_id, rank))
                    dev_MAP, dev_MRR = eval_map_mrr('data/output/WikiQA-dev.rank'.format(epoch), 'data/raw/WikiQA-dev.tsv')
                    print('Dev MAP: {}, MRR: {}'.format(dev_MAP, dev_MRR))
                    # print('{}\t{}\t{}\t{}\t{}\t{}\t{}'.format(epoch, cur_step, train_loss, dev_MAP, dev_MRR, test_MAP, test_MRR))
                    train_loss = 0
            print('Saving model for epoch {}'.format(epoch))
            saver.save(sess, checkpoint_model_path, global_step=epoch)


def gen_rank_for_test(checkpoint_model_path):
    data_helper = DataHelper()
    data_helper.restore('data/model/data_helper_info.bin')
    data_helper.prepare_test_data('data/lemmatized/WikiQA-test.tsv')
    lstm_model = QaLSTM(
        q_length=data_helper.max_q_length,
        a_length=data_helper.max_a_length,
        word_embeddings=data_helper.embeddings,
        LSTM_hidden_size=300,
        margin=0.25,
        l2_reg_lambda=0
    )
    saver = tf.train.Saver()
    with tf.Session() as sess:
        saver.restore(sess, checkpoint_model_path)
        # test on test set
        q_test, ans_test, q_length, ans_length = zip(*data_helper.test_data)
        similarity_scores = sess.run(lstm_model.pos_similarity, feed_dict={lstm_model.question: q_test,
                                                                           lstm_model.pos_answer: ans_test,
                                                                           lstm_model.question_length : q_length,
                                                                           lstm_model.pos_answer_length: ans_length,
        })
        for sample, similarity_score in zip(data_helper.test_samples, similarity_scores):
            # print('{}\t{}\t{}'.format(sample.q_id, sample.a_id, similarity_score))
            sample.score = similarity_score
        with open('data/output/WikiQA-test.rank', 'w') as fout:
            for sample, rank in get_final_rank(data_helper.test_samples):
                fout.write('{}\t{}\t{}\n'.format(sample.q_id, sample.a_id, rank))
        test_MAP, test_MRR = eval_map_mrr('data/output/WikiQA-test.rank', 'data/raw/WikiQA-test-gold.tsv')
        print('Test MAP: {}, MRR: {}'.format(test_MAP, test_MRR))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true', help='whether to prepare data helper')
    parser.add_argument('--train', action='store_true', help='train a model for answer selection')
    parser.add_argument('--test', action='store_true', help='generate the rank for test file')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    if args.prepare:
        prepare_helper()
    if args.train:
        train_lstm()
    if args.test:
        checkpoint_num = 9
        gen_rank_for_test(checkpoint_model_path='data/model/checkpoints/model.ckpt-{}'.format(checkpoint_num))
